<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'

const route = useRoute(); const router = useRouter()
const sid = Number(route.params.sid)
const sched = ref(null); const room = ref(null)
const msgs = ref([]); const hrs = ref([]); const votes = ref([])
const text = ref(''); const mtype = ref('danmaku')
const roll = ref(null)          // {batch, called}
const rollResult = ref(null)
const hb = ref({ on: false, total: 0 })
const recording = ref(null)
const voteForm = ref({ title: '', options: ['', '', ''] })

const isStudent = computed(() => auth.user.role === 'student')
const isTeacher = computed(() => auth.user.role === 'teacher')
const owner = computed(() => sched.value && auth.user.id === sched.value.teacher_id)
const living = computed(() => room.value && room.value.status === 'living')

async function load() {
  sched.value = await http.get(`/schedules/${sid}`)
  const r = await http.get(`/schedules/${sid}/room`)
  room.value = r && { ...r, push: undefined }
  if (room.value) await refresh()
}

async function refresh() {
  try {
    msgs.value = await http.get(`/rooms/${room.value.room_id}/messages`)
    votes.value = await http.get(`/rooms/${room.value.room_id}/votes`)
    if (owner.value) hrs.value = (await http.get(`/rooms/${room.value.room_id}/handraises`)).filter(h => h.status === 'waiting')
  } catch (e) { /* 直播间已关闭等情况忽略 */ }
}

let timer
onMounted(async () => {
  try { await load() } catch (e) { ElMessage.error(err(e)) }
  timer = setInterval(refresh, 3000)
})
onUnmounted(() => { clearInterval(timer); stopHB() })

async function send() {
  if (!text.value.trim()) return
  try { await http.post(`/rooms/${room.value.room_id}/messages`, { type: mtype.value, content: text.value }); text.value = ''; refresh() }
  catch (e) { ElMessage.error(err(e)) }
}
async function act(mid, a) { await http.post(`/rooms/${room.value.room_id}/messages/${mid}/${a}`); refresh() }
async function raise() { try { await http.post(`/rooms/${room.value.room_id}/handraises`); ElMessage.success('已举手，等待讲师处理') } catch (e) { ElMessage.error(err(e)) } }
async function handleHR(h, action) { await http.post(`/rooms/${room.value.room_id}/handraises/${h.id}/handle`, { action }); refresh() }
async function startRoll() { roll.value = await http.post(`/rooms/${room.value.room_id}/rollcall`); ElMessage.success(`点名已发起，应到 ${roll.value.called} 人`) }
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
  try {
    const d = await http.post(`/schedules/${sid}/start`)
    room.value = { room_id: d.room_id, schedule_id: sid, status: 'living', online_count: 0 }
    ElMessage.success('直播已开启（模拟推流：' + d.push_url + '）')
  } catch (e) { ElMessage.error(err(e)) }
}
async function stop() {
  recording.value = await http.post(`/rooms/${room.value.room_id}/stop`)
  room.value.status = 'ended'
  ElMessage.success('已停播，录制任务已生成')
}

let hbTimer
function toggleHB() {
  hb.value.on = !hb.value.on
  if (hb.value.on) {
    hbTimer = setInterval(async () => {
      try { await http.post(`/rooms/${room.value.room_id}/heartbeat`, { seconds: 30 }); hb.value.total += 30 }
      catch (e) { stopHB() }
    }, 4000)
  } else stopHB()
}
function stopHB() { hb.value.on = false; clearInterval(hbTimer) }
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
            <div style="font-size:44px">🎥</div>
            <div>{{ living ? '媒体流演示占位：SRS WebRTC 推拉流需部署流媒体服务后接入' : (room ? '本场直播已结束' : '等待讲师开播') }}</div>
            <div class="muted" v-if="living">信令/互动通道已连通（REST 模拟 WebSocket，每 3 秒增量刷新）</div>
          </div>
          <div style="margin-top:10px; display:flex; gap:12px; align-items:center" v-if="isStudent && room">
            <el-button size="small" :type="hb.on ? 'warning' : 'primary'" :disabled="!living" @click="toggleHB">
              {{ hb.on ? '停止模拟学习' : '模拟学习（每4秒上报30s心跳）' }}
            </el-button>
            <span>本次已计 <b>{{ hb.total }}</b> 秒 → watch_logs</span>
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
            <div v-if="roll" class="muted" style="margin-top:8px">点名批次 {{ roll.batch }} 进行中（应到{{ roll.called }}人）
              <el-button size="small" @click="closeRoll">结束点名</el-button>
            </div>
            <div v-if="rollResult" class="muted">上次点名结果：到 {{ rollResult.present }} / 缺 {{ rollResult.absent }}</div>
            <el-divider>发起投票</el-divider>
            <el-input v-model="voteForm.title" size="small" placeholder="投票标题" style="margin-bottom:6px" />
            <el-input v-for="(o, i) in voteForm.options" :key="i" v-model="voteForm.options[i]" size="small" :placeholder="`选项${i + 1}`" style="margin-bottom:4px" />
            <el-button size="small" type="primary" @click="createVote">发布（120秒）</el-button>
          </template>
          <template v-if="isStudent && living">
            <div style="display:flex;gap:8px">
              <el-button size="small" @click="raise">🖐 举手</el-button>
              <el-button size="small" type="warning" @click="respond">✋ 点名应答「到」</el-button>
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
            <div v-for="(n, opt) in v.result" :key="opt">
              <span style="display:inline-block;width:72px">{{ opt }}</span>
              <el-progress :percentage="v.participants ? Math.round(n * 100 / v.participants) : 0" :stroke-width="12" style="width:calc(100% - 84px); display:inline-flex" />
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
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.video-stage { height: 300px; background: #101418; color: #dfe4ea; border-radius: 8px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
</style>
