// 与 SRS 的 WebRTC 信令：WHIP 推流（老师）、WHEP 拉流（学生）。
// 停止时必须 DELETE 信令资源，SRS 才会立即收尾（DVR 原片随即定稿，而不是等 ICE 超时）。

async function signal(url, pc) {
  await pc.setLocalDescription(await pc.createOffer())
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp' },
    body: pc.localDescription.sdp,
  })
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    pc.close()
    throw new Error(`信令失败 HTTP ${resp.status} ${body.slice(0, 160)}`)
  }
  await pc.setRemoteDescription({ type: 'answer', sdp: await resp.text() })
  return resp.headers.get('Location')
}

function resourceUrl(url, location) {
  if (!location) return null
  try {
    return new URL(location, url).toString()
  } catch {
    return null
  }
}

export async function whipPublish(url, stream) {
  const pc = new RTCPeerConnection({ iceServers: [] })
  stream.getTracks().forEach((t) => pc.addTrack(t, stream))
  const location = await signal(url, pc)
  const resource = resourceUrl(url, location)
  return {
    pc,
    async close() {
      if (resource) await fetch(resource, { method: 'DELETE' }).catch(() => {})
      pc.close()
    },
  }
}

export async function whepPlay(url) {
  const pc = new RTCPeerConnection({ iceServers: [] })
  const stream = new MediaStream()
  pc.addTransceiver('video', { direction: 'recvonly' })
  pc.addTransceiver('audio', { direction: 'recvonly' })
  pc.ontrack = (e) => stream.addTrack(e.track)
  const location = await signal(url, pc)
  const resource = resourceUrl(url, location)
  return {
    pc,
    stream,
    async close() {
      if (resource) await fetch(resource, { method: 'DELETE' }).catch(() => {})
      pc.close()
    },
  }
}

// 老师端信号源：屏幕共享或摄像头+麦克风
export async function capture(source) {
  if (source === 'screen') {
    return navigator.mediaDevices.getDisplayMedia({ video: true, audio: true })
  }
  return navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: { echoCancellation: true },
  })
}

export function stopCapture(stream) {
  stream?.getTracks().forEach((t) => t.stop())
}

// 演示/自检用：无需摄像头权限的合成信号源（画布动画 + 音频振荡器）
export function syntheticStream(fps = 25) {
  const canvas = document.createElement('canvas')
  canvas.width = 1280; canvas.height = 720
  const c = canvas.getContext('2d')
  const t0 = Date.now()
  const timer = setInterval(() => {
    const t = (Date.now() - t0) / 1000
    c.fillStyle = '#101418'; c.fillRect(0, 0, 1280, 720)
    c.fillStyle = '#2ecc71'; c.fillRect((t * 120) % 1180, 300, 100, 100)
    c.fillStyle = '#ffffff'; c.font = '44px monospace'
    c.fillText(`DEMO LIVE ${t.toFixed(1)}s`, 60, 120)
  }, 1000 / fps)
  const stream = canvas.captureStream(fps)
  let ac = null
  try {
    ac = new AudioContext()
    const osc = ac.createOscillator()
    const dest = ac.createMediaStreamDestination()
    osc.frequency.value = 440
    osc.connect(dest)
    osc.start()
    dest.stream.getAudioTracks().forEach((t) => stream.addTrack(t))
  } catch { /* 无音频也不影响视频链路验证 */ }
  return {
    stream,
    stop() {
      clearInterval(timer)
      stopCapture(stream)
      ac?.close().catch(() => {})
    },
  }
}
