<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http, err } from '../api'
import { auth } from '../store'
import { whipPublish, whepPlay, capture, stopCapture } from '../webrtc'
import { ElMessage } from 'element-plus'

const route = useRoute(); const router = useRouter()
const sid = Number(route.params.sid)
const sched = ref(null); const room = ref(null)
const msgs = ref([]); const hrs = ref([]); const hrAll = ref([]); const votes = ref([])
const myHR = ref(null)
const text = ref(''); const mtype = ref('danmaku')
const roll = ref(null)          // {batch, called}
const rollActive = ref(null)    // 服务端进行中批次 {batch, called, present, mine}
const rollResult = ref(null)
const hb = ref({ on: false, paused: true, total: 0 })
const recording = ref(null)
const voteForm = ref({ title: '', options: ['', '', ''] })

const videoEl = ref(null)
const source = ref('camera')    // camera|screen
const mediaState = ref('idle')  // idle|pushing|playing|error
const mediaErr = ref('')
const needGesture = ref(false)  // 浏览器自动播放策略拦截
let session = null; let localStream = null

const isStudent = computed(() => auth.user.role === 'student')
const isTeacher = computed(() => auth.user.role === 'teacher')
const owner = computed(() => sched.value && auth.user.id === sched.value.teacher_id)
const living = computed(() => room.value && room.value.status === 'living')
const speaking = computed(() => hrAll.value.filter(h => h.status === 'accepted'))

async function load() {
  sched.value = await http.get(`/schedules/${sid}`)
  source.value = sched.value.mode === 'screen' ? 'screen' : 'camera'
  const r = await http.get(`/schedules/${sid}/room`)
  if (!r) return
  room.value = await http.get(`/rooms/${r.room_id}`)
  room.value.room_id = room.value.room_id ?? r.room_id
  await refresh()
  if (living.value && !owner.value) await startPull(room.value.pull_url)
}

async function refresh() {
  try {
    const st = await http.get(`/rooms/${room.value.room_id}`)
    if (st && st.status && st.status !== room.value.status) {
      room.value.status = st.status
      if (st.status !== 'living' && mediaState.value === 'playing') {
        stopHB(); teardownMedia(); mediaState.value = 'error'; mediaErr.value = '讲师已停播，本场直播结束（稍后可查看回放）'
      }
    }
    msgs.value = await http.get(`/rooms/${room.value.room_id}/messages`)
    votes.value = await http.get(`/rooms/${room.value.room_id}/votes`)
    if (owner.value) {
      hrAll.value = await http.get(`/rooms/${room.value.room_id}/handraises`)
      hrs.value = hrAll.value.filter(h => h.status === 'waiting')
    } else if (isStudent.value) {
      myHR.value = (await http.get(`/rooms/${room.value.room_id}/my_handraise`)).status
    }
    rollActive.value = await http.get(`/rooms/${room.value.room_id}/rollcall/active`)
    if (owner.value) roll.value = rollActive.value
  } catch (e) { /* 直播间已关闭等情况忽略 */ }
}

let timer
onMounted(async () => {
  try { await load() } catch (e) { ElMessage.error(err(e)) }
  timer = setInterval(refresh, 3000)
})
onUnmounted(() => { clearInterval(timer); stopHB(); teardownMedia() })

async function bindVideo(stream, muted) {
  if (!videoEl.value) await nextTick()
  if (!videoEl.value) return
  videoEl.value.srcObject = stream
  videoEl.value.muted = muted
  try { await videoEl.value.play() } catch { needGesture.value = true }
}
function resumePlay() { needGesture.value = false; videoEl.value?.play().catch(() => { needGesture.value = true }) }

async function startPush(pushUrl) {
  teardownMedia()
  localStream = await capture(source.value)
  session = await whipPublish(pushUrl, localStream)
  session.pc.onconnectionstatechange = () => {
    const st = session?.pc.connectionState
    if (st === 'failed') { mediaState.value = 'error'; mediaErr.value = '推流连接中断，请重试推流' }
  }
  await bindVideo(localStream, true)
  mediaState.value = 'pushing'
}

async function startPull(pullUrl) {
  teardownMedia()
  session = await whepPlay(pullUrl)
  session.pc.onconnectionstatechange = () => {
    const st = session?.pc.connectionState
    if (st === 'failed' || st === 'closed') { stopHB(); mediaState.value = 'error'; mediaErr.value = '讲师已停播，本场直播结束（稍后可查看回放）' }
  }
  await bindVideo(session.stream, false)
  mediaState.value = 'playing'
  if (isStudent.value) startHB()
}

function teardownMedia() {
  stopHB()
  session?.close(); session = null
  stopCapture(localStream); localStream = null
  if (videoEl.value) videoEl.value.srcObject = null
  if (mediaState.value !== 'error') mediaState.value = 'idle'
}

async function mediaError(e) {
  mediaState.value = 'error'
  mediaErr.value = String(e?.response?.data?.message || e?.message || e)
  ElMessage.error(mediaErr.value)
}

async function send() {
  if (!text.value.trim()) return
  try { await http.post(`/rooms/${room.value.room_id}/messages`, { type: mtype.value, content: text.value }); text.value = ''; refresh() }
  catch (e) { ElMessage.error(err(e)) }
}
async function act(mid, a) { await http.post(`/rooms/${room.value.room_id}/messages/${mid}/${a}`); refresh() }
async function raise() {
  try {
    await http.post(`/rooms/${room.value.room_id}/handraises`)
    myHR.value = 'waiting'
    ElMessage.success('已举手，等待讲师处理')
  } catch (e) { ElMessage.error(err(e)) }
}
async function lower() {
  try { await http.post(`/rooms/${room.value.room_id}/handraises/lower`); myHR.value = 'ended'; ElMessage.success('已下麦') }
  catch (e) { ElMessage.error(err(e)) }
}
async function handleHR(h, action) {
  try {
    await http.post(`/rooms/${room.value.room_id}/handraises/${h.id}/handle`, { action })
    ElMessage.success({ accept: `已同意 ${h.student} 连麦`, decline: `已婉拒 ${h.student}`, end: `已结束 ${h.student} 的连麦` }[action])
    refresh()
  } catch (e) { ElMessage.error(err(e)) }
}
async function startRoll() { const d = await http.post(`/rooms/${room.value.room_id}/rollcall`); ElMessage.success(`点名已发起，应到 ${d.called} 人`); refresh() }
async function respond() { try { await http.post(`/rooms/${room.value.room_id}/rollcall/respond`); ElMessage.success('已应答「到！」'); refresh() } catch (e) { ElMessage.error(err(e)) } }
async function closeRoll() { rollResult.value = await http.post(`/rooms/${room.value.room_id}/rollcall/close`, { batch: roll.value.batch }); roll.value = null }
async function createVote() {
  try {
    await http.post(`/rooms/${room.value.room_id}/votes`, { title: voteForm.value.title, options: voteForm.value.options.filter(Boolean), duration_seconds: 120 })
    voteForm.value = { title: '', options: ['', '', ''] }
    refresh()
  } catch (e) { ElMessage.error(err(e)) }
}
async function cast(v, idx) { try { await http.post(`/votes/${v.id}/cast`, { selected: [idx] }); refresh() } catch (e) { ElMessage.error(err(e)) } }

async function start() {
  // 一次点击完成：建房 -> 采集 -> WHIP 推流；SRS 收到流即自动开始服务端录制
  let d
  try {
    d = await http.post(`/schedules/${sid}/start`)
  } catch (e) { ElMessage.error(err(e)); return }
  room.value = { room_id: d.room_id, schedule_id: sid, status: 'living', online_count: 0,
                 push_url: d.push_url, pull_url: d.pull_url }
  if (!d.media_online) {
    mediaState.value = 'error'
    mediaErr.value = '流媒体服务(SRS)不可达，无法推流。请先执行 docker compose up -d srs'
    ElMessage.warning(mediaErr.value)
    return
  }
  try {
    await startPush(d.push_url)
    ElMessage.success('已开播推流，服务端自动录制中')
  } catch (e) { await mediaError(e) }
}

async function repush() {
  try {
    await startPush(room.value.push_url)
    ElMessage.success('推流已恢复')
  } catch (e) { await mediaError(e) }
}

async function stopPush() {
  teardownMedia()
  ElMessage.info('已停止推流（60 秒内可重新推流继续；超时服务端自动收尾生成回放）')
}

async function stop() {
  try {
    recording.value = await http.post(`/rooms/${room.value.room_id}/stop`)
    room.value.status = 'ended'
    teardownMedia()
    ElMessage.success('已停播，录制原片已定稿，后台自动转码回放')
  } catch (e) { ElMessage.error(err(e)) }
}

// 观看时长由真实播放进度推导：暂停 / 回退 / 断流跳转产生的时间差都不计入
let hbTimer = null, accSec = 0, lastT = 0
function startHB() {
  stopHB()
  accSec = 0
  lastT = videoEl.value ? videoEl.value.currentTime : 0
  hb.value.on = true
  hbTimer = setInterval(async () => {
    const v = videoEl.value
    if (!v) return
    hb.value.paused = !!v.paused
    const d = v.currentTime - lastT
    lastT = v.currentTime
    if (v.paused || d <= 0 || d > 10) return
    accSec += d
    if (accSec >= 30) {
      const secs = Math.min(60, Math.round(accSec)); accSec = 0
      try {
        await http.post(`/rooms/${room.value.room_id}/heartbeat`, { seconds: secs })
        hb.value.total += secs
      } catch (e) { stopHB() }
    }
  }, 2000)
}
function stopHB() { hb.value.on = false; hb.value.paused = true; clearInterval(hbTimer); hbTimer = null }
</script>

<template>
  <div class="page" v-if="sched">
    <el-row :gutter="16">
      <el-col :span="16">
        <el-card class="card-gap">
          <template #header>
            <b>{{ sched.title }}</b>
            <el-tag :type="living ? 'danger' : 'info'" style="margin-left:8px" size="small">{{ living ? '● 直播中' : (room ? '已结束' : '未开播') }}</el-tag>
            <span class="muted" style="margin-left:8px">排课#{{ sid }} · {{ sched.mode }} 模式</span>
            <div style="float:right">
              <el-button v-if="owner && !room" size="small" type="danger" @click="start">开 播</el-button>
              <el-button v-if="owner && living" size="small" @click="stop">停 播</el-button>
              <el-button v-if="recording" size="small" type="success" @click="router.push(`/replay/${sid}`)">查看回放</el-button>
            </div>
          </template>
          <div class="video-stage">
            <video ref="videoEl" autoplay playsinline controls></video>
            <div v-if="mediaState === 'error'" class="stage-mask">{{ mediaErr }}</div>
            <div v-else-if="needGesture" class="stage-mask" @click="resumePlay">▶ 点击开始播放</div>
            <div v-else-if="mediaState !== 'pushing' && mediaState !== 'playing'" class="stage-mask">
              {{ living ? (owner ? '未推流：选好信号源后点「开播」或「开始推流」' : '等待讲师推流…') : (room ? '本场直播已结束，去回放页观看' : '等待讲师开播') }}
            </div>
          </div>
          <div style="margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
            <template v-if="owner">
              <el-radio-group v-model="source" size="small" :disabled="mediaState === 'pushing'">
                <el-radio-button value="camera">摄像头+麦克风</el-radio-button>
                <el-radio-button value="screen">屏幕共享</el-radio-button>
              </el-radio-group>
              <el-button v-if="living && mediaState !== 'pushing'" size="small" type="primary" @click="repush">开始推流</el-button>
              <el-button v-if="mediaState === 'pushing'" size="small" @click="stopPush">停止推流</el-button>
            </template>
            <el-tag v-if="living" type="danger" size="small">🔴 服务端自动录制中（SRS DVR）</el-tag>
            <el-tag v-if="mediaState === 'pushing'" type="success" size="small">推流中 · {{ source === 'screen' ? '屏幕共享' : '摄像头' }}</el-tag>
            <el-tag v-if="mediaState === 'playing'" type="success" size="small">已连通 WebRTC 低延迟拉流</el-tag>
            <span class="muted">{{ living ? '停播后录制原片自动转码为回放，学生可在回放页观看' : '信令/互动通道每 3 秒增量刷新' }}</span>
          </div>
          <div style="margin-top:10px; display:flex; gap:12px; align-items:center" v-if="isStudent && room">
            <el-tag :type="!hb.on ? 'info' : (hb.paused ? 'warning' : 'success')" size="small">
              {{ !hb.on ? '未计时（画面未播放）' : (hb.paused ? '⏸ 已暂停，暂停期间不计时' : '● 观看计时进行中（按真实播放进度上报）') }}
            </el-tag>
            <span>本次已计 <b>{{ hb.total }}</b> 秒 → watch_logs，每累计 30 秒有效播放上报一次</span>
          </div>
          <el-alert v-if="recording" type="success" :closable="false" style="margin-top:10px"
            :title="`录制任务 #${recording.recording_id} 状态：${recording.recording_status}（转码完成后自动上架回放）`" />
        </el-card>

        <el-card class="card-gap">
          <template #header>弹幕 / 提问（{{ msgs.length }} 条）</template>
          <div class="danmaku-list">
            <div v-for="m in msgs" :key="m.id">
              <el-tag size="small" :type="m.type === 'question' ? 'warning' : 'primary'">{{ m.type === 'question' ? '提问' : '弹幕' }}</el-tag>
              <b style="margin:0 6px">{{ m.student }}</b>{{ m.content }}
              <el-tag v-if="m.status === 'answered'" size="small" type="success" style="margin-left:6px">已解答</el-tag>
              <template v-if="owner && living && room && room.status === 'living'">
                <el-button size="small" link type="danger" style="float:right" @click="act(m.id, 'recall')">撤回</el-button>
                <el-button v-if="m.type === 'question' && m.status === 'normal'" size="small" link type="success" style="float:right" @click="act(m.id, 'answer')">标记解答</el-button>
              </template>
            </div>
            <p v-if="!msgs.length" class="muted">暂无发言</p>
          </div>
          <div style="display:flex; gap:8px; margin-top:10px" v-if="isStudent && room">
            <el-select v-model="mtype" style="width:96px" size="small"><el-option label="弹幕" value="danmaku" /><el-option label="提问" value="question" /></el-select>
            <el-input v-model="text" size="small" placeholder="发送消息（≤200字）" @keyup.enter="send" />
            <el-button size="small" type="primary" :disabled="!living" @click="send">发送</el-button>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card class="card-gap">
          <template #header>互动工具</template>
          <template v-if="owner && living">
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <el-button size="small" @click="startRoll" :disabled="!!roll">发起点名</el-button>
            </div>
            <div v-if="roll" class="muted" style="margin-top:8px">点名批次 {{ roll.batch }} 进行中（应到{{ roll.called }} · 已到{{ roll.present }}）
              <el-button size="small" @click="closeRoll">结束点名</el-button>
            </div>
            <div v-if="rollResult" class="muted">上次点名结果：到 {{ rollResult.present }} / 缺 {{ rollResult.absent }}</div>
            <el-divider>发起投票</el-divider>
            <el-input v-model="voteForm.title" size="small" placeholder="投票标题" style="margin-bottom:6px" />
            <el-input v-for="(o, i) in voteForm.options" :key="i" v-model="voteForm.options[i]" size="small" :placeholder="`选项${i + 1}`" style="margin-bottom:4px" />
            <el-button size="small" type="primary" @click="createVote">发布（120秒）</el-button>
          </template>
          <template v-if="isStudent && living">
            <div style="display:flex;gap:8px;align-items:center">
              <el-button size="small" :disabled="myHR === 'waiting'" @click="raise">🖐 举手</el-button>
              <el-tag v-if="myHR === 'waiting'" type="warning" size="small">✋ 已举手，等待讲师处理</el-tag>
              <el-tag v-else-if="myHR === 'accepted'" type="success" size="small">🎤 讲师已同意连麦</el-tag>
              <el-button v-if="myHR === 'accepted'" size="small" @click="lower">🔽 下麦</el-button>
              <el-tag v-else-if="myHR === 'declined'" type="info" size="small">连麦申请已被婉拒</el-tag>
            </div>
            <div v-if="rollActive && rollActive.mine === 'pending'" class="roll-alert">
              📢 点名进行中（已到 {{ rollActive.present }}/{{ rollActive.called }}）
              <el-button size="small" type="danger" @click="respond">✋ 点「到」应答</el-button>
            </div>
            <div v-else-if="rollActive && rollActive.mine === 'present'" style="margin-top:8px">
              📢 点名进行中
              <el-tag type="success" size="small">已应答「到！」</el-tag>
            </div>
            <div v-for="v in votes.filter(x => x.status === 'open')" :key="v.id" style="margin-top:8px">
              <b>{{ v.title }}</b>
              <div v-for="(o, i) in v.options" :key="o" style="margin:4px 0">
                <el-button size="small" :disabled="!!v.mine" @click="cast(v, i)">{{ o }}</el-button>
              </div>
            </div>
          </template>
          <el-divider v-if="votes.length">投票结果</el-divider>
          <div v-for="v in votes" :key="v.id" style="margin-bottom:8px">
            <b>{{ v.title }}</b><span class="muted">（{{ v.status === 'open' ? '进行中' : '已结束' }}，{{ v.participants }}人）</span>
            <div v-for="item in v.result" :key="item.option + v.id">
              <span style="display:inline-block;width:72px">{{ item.option }}</span>
              <el-progress :percentage="v.participants ? Math.round(item.count * 100 / v.participants) : 0" :stroke-width="12" style="width:calc(100% - 84px); display:inline-flex" />
            </div>
          </div>
        </el-card>

        <el-card v-if="owner">
          <template #header>举手队列（{{ hrs.length }}）</template>
          <div v-for="h in hrs" :key="h.id" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <span>{{ h.student }}</span>
            <span>
              <el-button size="small" type="success" @click="handleHR(h, 'accept')">连麦</el-button>
              <el-button size="small" @click="handleHR(h, 'decline')">婉拒</el-button>
            </span>
          </div>
          <p v-if="!hrs.length" class="muted">当前无人举手</p>
        </el-card>

        <el-card v-if="owner && speaking.length">
          <template #header>🎤 连麦中（{{ speaking.length }}）</template>
          <div v-for="h in speaking" :key="h.id" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <span>{{ h.student }}</span>
            <span>
              <el-tag type="success" size="small">已连麦</el-tag>
              <el-button size="small" @click="handleHR(h, 'end')">结束连麦</el-button>
            </span>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.roll-alert {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #fef0f0;
  border: 1px solid #fbc4c4;
  color: #c45656;
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
}
.video-stage { height: 320px; background: #101418; color: #dfe4ea; border-radius: 8px; position: relative; overflow: hidden; }
.video-stage video { width: 100%; height: 100%; object-fit: contain; background: #000; display: block; }
.stage-mask { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center; padding: 0 24px; background: rgba(16, 20, 24, 0.92); color: #dfe4ea; font-size: 14px; cursor: pointer; }
</style>
