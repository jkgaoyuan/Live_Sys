"""停播收尾与录制转码任务编排。

正常停播由 /rooms/{rid}/stop 触发；讲师直接关页面/断流超时则由 reaper 兜底，
两条路径共用同一个后台任务：等原片定稿 -> 转 HLS -> 回写回放状态。
"""
import logging
import threading
import time

from sqlalchemy.orm import Session

from . import media
from .database import SessionLocal
from .deps import now
from .models import LiveRoom, Recording, Schedule

log = logging.getLogger("recording")

REAPER_INTERVAL = 10   # 秒，断流扫描周期
OFFLINE_GRACE = 60     # 秒，断流多久判定停播（对齐 PRD「讲师断流 60 秒内可恢复」）

_absent_since: dict[int, float] = {}
_lock = threading.Lock()


def replay_dir(rec_id: int):
    return media.REPLAY_DIR / f"rec_{rec_id}"


def replay_hls_url(rec_id: int) -> str:
    return f"/api/v1/recordings/{rec_id}/hls/index.m3u8"


def create_recording(db: Session, room: LiveRoom) -> Recording:
    """一个排课只有一条回放；重复调用返回既有记录（幂等）。"""
    rec = db.query(Recording).filter_by(schedule_id=room.schedule_id).first()
    if rec is None:
        rec = Recording(schedule_id=room.schedule_id, status="transcoding")
        db.add(rec)
        db.commit()
        db.refresh(rec)
    return rec


def process(rec_id: int, stream_key: str):
    db = SessionLocal()
    try:
        rec = db.get(Recording, rec_id)
        if rec is None or rec.status != "transcoding":
            return
        if not media.wait_publish_closed(stream_key):
            log.warning("rec=%s 未确认 %s 断流，按原片现状继续处理", rec_id, stream_key)
        src = media.wait_dvr_final(stream_key)
        if src is None:
            rec.status = "failed"
            rec.error_message = "未找到 SRS 录制原片，请确认流媒体服务已启动"
            db.commit()
            return
        rec.file_path = src.relative_to(media.MEDIA_DIR).as_posix()
        db.commit()
        playlist = media.transcode_to_hls(src, replay_dir(rec_id))
        rec.hls_url = replay_hls_url(rec_id)
        rec.duration = media.ffprobe_duration(playlist) or media.ffprobe_duration(src)
        rec.status = "ready"
        rec.error_message = ""
        db.commit()
        log.info("rec=%s 回放就绪 duration=%ss", rec_id, rec.duration)
    except Exception as exc:
        log.exception("rec=%s 转码异常", rec_id)
        db.rollback()
        rec = db.get(Recording, rec_id)
        if rec is not None:
            rec.status = "failed"
            rec.error_message = f"转码失败: {str(exc)[:180]}"
            db.commit()
    finally:
        db.close()


def spawn(rec_id: int, stream_key: str):
    threading.Thread(target=process, args=(rec_id, stream_key), daemon=True).start()


def _end_room(db: Session, room: LiveRoom) -> Recording:
    room.status = "ended"
    room.ended_at = now()
    s = db.get(Schedule, room.schedule_id)
    if s is not None and s.status == "living":
        s.status = "finished"
    return create_recording(db, room)


def reap_once():
    """扫描仍标记直播中、但 SRS 上已无推流端的直播间，自动收尾生成回放。"""
    names = media.publishing_streams()
    if names is None:          # SRS 不可达时不做判定，避免误结束
        return
    db = SessionLocal()
    try:
        for room in db.query(LiveRoom).filter_by(status="living").all():
            with _lock:
                if room.stream_key in names:
                    _absent_since.pop(room.id, None)
                    continue
                first_absent = _absent_since.setdefault(room.id, time.time())
                if time.time() - first_absent < OFFLINE_GRACE:
                    continue
                _absent_since.pop(room.id, None)
            if db.query(Recording).filter_by(schedule_id=room.schedule_id).first():
                continue
            rec = _end_room(db, room)
            db.commit()
            log.info("直播间 %s 断流超时，服务端自动收尾 rec=%s", room.id, rec.id)
            spawn(rec.id, room.stream_key)
    finally:
        db.close()


def start_worker():
    media.ensure_dirs()
    db = SessionLocal()
    try:  # 后端重启后接续未完成的转码任务
        for rec in db.query(Recording).filter_by(status="transcoding").all():
            room = db.query(LiveRoom).filter_by(schedule_id=rec.schedule_id).first()
            if room is not None:
                spawn(rec.id, room.stream_key)
    finally:
        db.close()

    def loop():
        while True:
            time.sleep(REAPER_INTERVAL)
            try:
                reap_once()
            except Exception:
                log.exception("录制 reaper 异常")

    threading.Thread(target=loop, daemon=True).start()
