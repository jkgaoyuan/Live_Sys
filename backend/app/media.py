"""SRS 流媒体接入与服务端录制转码。

真实媒体管线（非占位）：浏览器 WHIP 推流 -> SRS -> 在线 HLS/HTTP-FLV/WebRTC 拉流，
SRS DVR 服务端自动录制 mp4 原片 -> 后端 ffmpeg 转 HLS VOD 供回放。
"""
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger("media")

MEDIA_DIR = Path(__file__).resolve().parent.parent / "storage" / "media"
DVR_DIR = MEDIA_DIR / "dvr" / "live"
REPLAY_DIR = MEDIA_DIR / "replay"

SRS_PUBLIC_HOST = os.environ.get("SRS_PUBLIC_HOST", "127.0.0.1")
SRS_API_URL = os.environ.get("SRS_API_URL", f"http://{SRS_PUBLIC_HOST}:1985")
SRS_HTTP_URL = os.environ.get("SRS_HTTP_URL", f"http://{SRS_PUBLIC_HOST}:8080")
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")

# 转码是 CPU 密集操作，同一时刻只放行一个任务
_transcode_slot = threading.Semaphore(1)


def ensure_dirs():
    for d in (DVR_DIR, REPLAY_DIR):
        d.mkdir(parents=True, exist_ok=True)


def whip_url(stream: str) -> str:
    return f"{SRS_API_URL}/rtc/v1/whip/?app=live&stream={stream}"


def whep_url(stream: str) -> str:
    return f"{SRS_API_URL}/rtc/v1/whep/?app=live&stream={stream}"


def media_reachable() -> bool:
    try:
        return httpx.get(f"{SRS_API_URL}/api/v1/versions/", timeout=3).status_code == 200
    except Exception:
        return False


def publishing_streams():
    """SRS 当前正在推流的 stream 名集合；SRS 不可达时返回 None（区别于「已断流」）。"""
    try:
        resp = httpx.get(f"{SRS_API_URL}/api/v1/clients/", timeout=5)
        resp.raise_for_status()
        return {c.get("name") for c in resp.json().get("clients", []) if c.get("publish")}
    except Exception as exc:
        log.warning("SRS API 不可达: %s", exc)
        return None


def wait_publish_closed(stream: str, timeout: float = 40) -> bool:
    """等待该流的推流端断开（DVR 原片要等断流才定稿）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        names = publishing_streams()
        if names is None:
            return False
        if stream not in names:
            return True
        time.sleep(1)
    return False


def dvr_final_file(stream: str):
    """已定稿的录制原片（录制中为 .mp4.tmp，断流后由 SRS 改名为 .mp4）。"""
    files = sorted(DVR_DIR.glob(f"{stream}.*.mp4"))
    return files[-1] if files else None


def wait_dvr_final(stream: str, timeout: float = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        f = dvr_final_file(stream)
        if f is not None:
            size = f.stat().st_size
            time.sleep(1)
            if size > 0 and f.stat().st_size == size:
                return f
        time.sleep(1)
    return dvr_final_file(stream)


def ffprobe_duration(path: Path) -> int:
    try:
        out = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
        return int(float(out.stdout.strip() or 0))
    except Exception as exc:
        log.warning("ffprobe 失败 %s: %s", path, exc)
        return 0


def transcode_to_hls(src: Path, out_dir: Path) -> Path:
    """录制原片 -> HLS VOD（m3u8 + ts 切片），回放播放器直接消费。"""
    ensure_dirs()
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist = out_dir / "index.m3u8"
    seg = str(out_dir / "seg-%03d.ts")
    base = ["-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    hls = ["-hls_time", "4", "-hls_list_size", "0", "-hls_playlist_type", "vod",
           "-hls_segment_filename", seg, "-f", "hls", str(playlist)]
    with _transcode_slot:
        # DVR 原片已是 H.264/AAC，先尝试直封（快），失败再重编码（兼容异常时间戳）
        plans = [["-c", "copy"],
                 ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                  "-c:a", "aac", "-ar", "44100"]]
        last_err = ""
        for codec in plans:
            done = subprocess.run([FFMPEG_BIN, *base, *codec, *hls],
                                  capture_output=True, text=True, timeout=3600)
            if done.returncode == 0 and playlist.exists():
                return playlist
            last_err = (done.stderr or "").strip()[-400:]
            log.warning("转码方案失败，尝试下一个: %s", last_err)
    raise RuntimeError(f"HLS 转码失败: {last_err}")
