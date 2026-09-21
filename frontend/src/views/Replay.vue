<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http, err, download, API_ORIGIN } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'
import Hls from 'hls.js'

const route = useRoute(); const router = useRouter()
const sid = Number(route.params.sid)
const rec = ref(null)
const videoEl = ref(null)
const pos = ref(0)
const total = ref(0)
const rate = ref(1)
const resumeAt = ref(0)
const isTeacher = computed(() => auth.user.role === 'teacher')
const isStaff = computed(() => ['teacher', 'admin'].includes(auth.user.role))
const isAdmin = computed(() => auth.user.role === 'admin')

let hls = null
let acc = 0
let lastT = 0
let poll = null

async function load() {
  try {
    rec.value = await http.get(`/schedules/${sid}/recording`)
    pos.value = rec.value.last_position || 0
    total.value = rec.value.my_seconds || 0
    resumeAt.value = rec.value.last_position || 0
    if (rec.value.status === 'ready') { await nextTick(); mountPlayer() }
    else destroyPlayer()
    if (rec.value.status === 'transcoding' && !poll) poll = setInterval(load, 5000)
    else if (rec.value.status !== 'transcoding') { clearInterval(poll); poll = null }
  } catch (e) { ElMessage.error(err(e)) }
}
onMounted(load)
onUnmounted(() => { clearInterval(poll); flush(); destroyPlayer() })

function mountPlayer() {
  if (hls || !videoEl.value) return
  const url = `${API_ORIGIN}${rec.value.hls_url}`
  if (Hls.isSupported()) {
    hls = new Hls({ xhrSetup: (xhr) => xhr.setRequestHeader('Authorization', `Bearer ${auth.token}`) })
    hls.loadSource(url)
    hls.attachMedia(videoEl.value)
    hls.on(Hls.Events.MANIFEST_PARSED, seekResume)
  } else if (videoEl.value.canPlayType('application/vnd.apple.mpegurl')) {
    videoEl.value.src = url
    videoEl.value.addEventListener('loadedmetadata', seekResume)
  }
}
function destroyPlayer() {
  hls?.destroy(); hls = null
  if (videoEl.value) { videoEl.value.pause(); videoEl.value.removeAttribute('src'); videoEl.value.load?.() }
}
function seekResume() {
  if (!videoEl.value || !resumeAt.value) return
  const max = rec.value.duration || 0
  if (resumeAt.value < max) {
    videoEl.value.currentTime = resumeAt.value
    ElMessage.info(`已从上次观看位置 ${resumeAt.value} 秒续播`)
  }
  resumeAt.value = 0
}

function onPlay() { lastT = videoEl.value?.currentTime || 0 }
function onTimeUpdate() {
  const v = videoEl.value
  if (!v) return
  const d = v.currentTime - lastT
  lastT = v.currentTime
  pos.value = Math.floor(v.currentTime)
  if (d > 0 && d < 2) acc += d          // 跳转/回退不计入有效观看时长
  if (acc >= 30) { report(Math.round(acc)); acc = 0 }
}
function flush() { if (acc >= 1) { report(Math.round(acc)); acc = 0 } }

async function report(seconds) {
  if (auth.user.role !== 'student' || !rec.value) return
  try {
    const d = await http.put(`/recordings/${rec.value.id}/heartbeat`, { seconds, position: pos.value })
    total.value = d.total_seconds
  } catch (e) { /* 未选课/回放未就绪等忽略，不打断观看 */ }
}

function setRate(r) {
  rate.value = r
  if (videoEl.value) videoEl.value.playbackRate = r
}

async function retranscode() {
  try {
    await http.post(`/recordings/${rec.value.id}/retranscode`)
    ElMessage.success('已重新发起转码，完成后自动上架')
    load()
  } catch (e) { ElMessage.error(err(e)) }
}
async function remove() {
  try {
    await http.delete(`/recordings/${rec.value.id}`)
    ElMessage.success('回放及录制原片已删除')
    router.push(`/schedule`)
  } catch (e) { ElMessage.error(err(e)) }
}
async function archive() {
  try {
    await download(`/recordings/${rec.value.id}/download`, null, `recording_${rec.value.id}.mp4`)
  } catch (e) { ElMessage.error(err(e)) }
}
</script>

<template>
  <div class="page" v-if="rec">
    <el-card>
      <template #header>
        录播回放 · 排课 #{{ sid }}（录制 #{{ rec.id }}）
        <div style="float:right">
          <el-button v-if="rec.status === 'ready' && isAdmin" size="small" @click="archive">下载归档</el-button>
          <el-button v-if="rec.can_manage && rec.status !== 'transcoding'" size="small" @click="retranscode">重新生成回放</el-button>
          <el-button v-if="rec.can_manage" size="small" type="danger" @click="remove">删除回放</el-button>
        </div>
      </template>

      <el-alert v-if="rec.status === 'transcoding'" type="warning" :closable="false"
        title="服务端录制原片已生成，正在自动转码为 HLS 回放，完成后本页自动刷新（无需人工干预）" />
      <el-alert v-else-if="rec.status === 'failed'" type="error" :closable="false"
        :title="`转码失败：${rec.error_message || '未知原因'}`" />

      <template v-if="rec.status === 'ready'">
        <div class="video-stage">
          <video ref="videoEl" controls autoplay playsinline
                 @play="onPlay" @timeupdate="onTimeUpdate" @pause="flush" @ended="flush"></video>
        </div>
        <div style="margin:14px 0;display:flex;gap:14px;align-items:center;flex-wrap:wrap">
          <span>倍速</span>
          <el-radio-group v-model="rate" size="small" @change="setRate">
            <el-radio-button v-for="r in [0.75, 1, 1.25, 1.5, 2]" :key="r" :value="r">{{ r }}x</el-radio-button>
          </el-radio-group>
          <span class="muted">时长 {{ Math.floor(rec.duration / 60) }} 分 {{ rec.duration % 60 }} 秒</span>
          <span class="muted">当前位置 {{ pos }} 秒</span>
        </div>
        <div>
          服务端累计有效观看：<b>{{ total }}</b> 秒
          <span class="muted">（真实播放进度每满 30 秒上报一次，快进/跳转不计入；{{ isTeacher ? '教师端不计入观看时长' : '刷新页面将从上次位置续播' }}）</span>
        </div>
        <p class="muted" style="margin-top:10px">播放源为 SRS DVR 原片转码出的 HLS 切片，经后端按选课关系鉴权后下发</p>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.video-stage { background: #101418; border-radius: 8px; overflow: hidden; margin-top: 10px; }
.video-stage video { width: 100%; max-height: 460px; background: #000; display: block; }
</style>
