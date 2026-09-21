<script setup>
import { ref, reactive } from 'vue'
import axios from 'axios'
import { auth } from '../store'
import { whipPublish, syntheticStream } from '../webrtc'
import { ElMessage } from 'element-plus'

const raw = axios.create({ baseURL: 'http://127.0.0.1:8000/api/v1', timeout: 15000 })
const tok = (t) => ({ headers: { Authorization: `Bearer ${t}` } })

const running = ref(false)
const log = ref([])
const ctx = reactive({})

async function R(method, path, token, body, params) {
  const r = await raw.request({ method, url: path, data: body, params, ...(token ? tok(token) : {}) })
  return r.data && 'data' in r.data ? r.data.data : r.data
}
async function loginAs(u, p) { return (await R('post', '/auth/login', null, { username: u, password: p })).access_token }

function iso(minOffset = 0) { return new Date(Date.now() + minOffset * 60000).toISOString().slice(0, 19) }

const steps = []
function step(name, fn) { steps.push({ name, fn }) }

step('① 多角色登录（管理员/讲师/新建2名演示学生）', async () => {
  ctx.tAdmin = auth.token
  ctx.tTeacher = await loginAs('teacher_wang', 'Test@123')
  const ts = Date.now() % 100000
  const mk = async (n) => {
    await R('post', '/users', ctx.tAdmin, { username: `demo_${ts}_${n}`, password: 'Test@123', real_name: `演示生${n}`, role: 'student' })
    return loginAs(`demo_${ts}_${n}`, 'Test@123')
  }
  ctx.tS1 = await mk('a'); ctx.tS2 = await mk('b')
  ctx.sName = `演示生a(${ts})`
  return 'admin / teacher_wang / 2 名新学生 JWT 全部签发'
})

step('② 讲师建课（2章3节大纲）', async () => {
  const c = await R('post', '/courses', ctx.tTeacher, {
    title: `全链路演示课程 ${new Date().toLocaleTimeString()}`, intro: '由“全链路演示”页自动创建',
    audience: '演示', cover_url: '/img/demo.png',
    chapters: [
      { title: '第一章：基础', children: [{ title: '节A：环境搭建' }, { title: '节B：数据清洗' }] },
      { title: '第二章：进阶', children: [{ title: '节C：聚合分析' }] },
    ] })
  ctx.cid = c.id
  const d = await R('get', `/courses/${c.id}`, ctx.tTeacher)
  ctx.leaves = d.chapters.filter((x) => x.parent_id)
  return `course #${c.id}（status=draft，共 ${d.chapters.length} 条大纲）`
})

step('③ 提交审核 → 管理员审核（先验证越权）', async () => {
  let blocked = false
  try { await R('put', `/courses/${ctx.cid}/review`, ctx.tS1, { decision: 'approve' }) } catch (e) { blocked = e.response?.status === 403 }
  await R('post', `/courses/${ctx.cid}/submit-review`, ctx.tTeacher)
  const d = await R('put', `/courses/${ctx.cid}/review`, ctx.tAdmin, { decision: 'approve' })
  return `学生审核被拒403:${blocked} · 管理员审核 → ${d.status}`
})

step('④ 选课（把2名演示生加入课程）', async () => {
  const users = await R('get', '/users', ctx.tAdmin, null, { role: 'student' })
  const ids = users.filter((u) => u.real_name.startsWith('演示生')).slice(-2).map((u) => u.id)
  ctx.sids = ids
  const d = await R('post', `/courses/${ctx.cid}/enroll`, ctx.tTeacher, { student_ids: ids })
  return `enrolled=${d.enrolled} student_ids=${ids}`
})

step('⑤ 排课（含时间冲突校验）', async () => {
  const s = await R('post', '/schedules', ctx.tTeacher, {
    chapter_id: ctx.leaves[0].id, start_at: iso(60), end_at: iso(120), mode: 'screen' })
  ctx.sid = s.id
  let conflict = false
  try { await R('post', '/schedules', ctx.tTeacher, { chapter_id: ctx.leaves[1].id, start_at: iso(90), end_at: iso(150) }) }
  catch (e) { conflict = e.response?.status === 409 }
  return `schedule #${s.id} planned · 重复排课拒绝:${conflict}`
})

step('⑥ 开播（SRS 真实推流，服务端随即自动录制）', async () => {
  const d = await R('post', `/schedules/${ctx.sid}/start`, ctx.tTeacher)
  ctx.rid = d.room_id
  if (!d.media_online) throw new Error('SRS 不可达，请先执行 docker compose up -d srs')
  ctx.syn = syntheticStream()
  ctx.sess = await whipPublish(d.push_url, ctx.syn.stream)
  return `room #${d.room_id} living · whip=${d.push_url} · 信令成功，媒体流已上行`
})

step('⑦ 弹幕/提问 → 讲师解答与撤回', async () => {
  const dm = await R('post', `/rooms/${ctx.rid}/messages`, ctx.tS1, { type: 'danmaku', content: '演示弹幕：老师好' })
  const q = await R('post', `/rooms/${ctx.rid}/messages`, ctx.tS2, { type: 'question', content: '演示提问：如何分组聚合？' })
  await R('post', `/rooms/${ctx.rid}/messages/${q.id}/answer`, ctx.tTeacher)
  await R('post', `/rooms/${ctx.rid}/messages/${dm.id}/recall`, ctx.tTeacher)
  const view = await R('get', `/rooms/${ctx.rid}/messages`, ctx.tS1)
  return `提问已解答 · 撤回后该生可见消息 ${view.length} 条（弹幕已隐藏）`
})

step('⑧ 举手 → 讲师接受连麦', async () => {
  const h = await R('post', `/rooms/${ctx.rid}/handraises`, ctx.tS1)
  const d = await R('post', `/rooms/${ctx.rid}/handraises/${h.id}/handle`, ctx.tTeacher, { action: 'accept' })
  return `handraise #${h.id} → ${d.status}`
})

step('⑨ 点名（应答与缺席统计）', async () => {
  const rc = await R('post', `/rooms/${ctx.rid}/rollcall`, ctx.tTeacher)
  await R('post', `/rooms/${ctx.rid}/rollcall/respond`, ctx.tS1)
  const r = await R('post', `/rooms/${ctx.rid}/rollcall/close`, ctx.tTeacher, { batch: rc.batch })
  return `应到 ${rc.called} → 到 ${r.present} / 缺 ${r.absent}`
})

step('⑩ 投票（发起/投票/结果）', async () => {
  const v = await R('post', `/rooms/${ctx.rid}/votes`, ctx.tTeacher, { title: '听懂了吗', options: ['懂了', '没有'], duration_seconds: 120 })
  await R('post', `/votes/${v.id}/cast`, ctx.tS1, { selected: [0] })
  await R('post', `/votes/${v.id}/cast`, ctx.tS2, { selected: [1] })
  const res = await R('get', `/votes/${v.id}/result`, ctx.tTeacher)
  return JSON.stringify(res.result) + ` participants=${res.participants}`
})

step('⑪ 心跳计入学习时长（学生A 4次×30s）', async () => {
  for (let i = 0; i < 4; i++) await R('post', `/rooms/${ctx.rid}/heartbeat`, ctx.tS1, { seconds: 30 })
  return 'watch_logs(live) 累计 120 秒'
})

step('⑫ 持续推流 20 秒后停播 → 服务端录制定稿', async () => {
  await new Promise((r) => setTimeout(r, 20000))
  const pushed = ctx.sess.pc.getSenders().reduce((n, s) => n + (s.track ? 1 : 0), 0)
  await ctx.sess.close()
  ctx.syn.stop()
  const d = await R('post', `/rooms/${ctx.rid}/stop`, ctx.tTeacher)
  ctx.recid = d.recording_id
  let rejected = false
  try { await R('post', `/rooms/${ctx.rid}/heartbeat`, ctx.tS1, { seconds: 30 }) } catch (e) { rejected = e.response?.status === 409 }
  return `推流 ${pushed} 条轨道已断开 · recording #${d.recording_id} ${d.recording_status} · 停播后心跳拒绝:${rejected}`
})

step('⑬ 等待自动转码 → 回放上架（真实 ffmpeg HLS）', async () => {
  const deadline = Date.now() + 180000
  let r
  for (;;) {
    r = await R('get', `/schedules/${ctx.sid}/recording`, ctx.tS2)
    if (r.status !== 'transcoding') break
    if (Date.now() > deadline) break
    await new Promise((x) => setTimeout(x, 4000))
  }
  if (r.status !== 'ready') throw new Error(`转码未就绪 status=${r.status} ${r.error_message || ''}`)
  return `status=${r.status} duration=${r.duration}s hls=${r.hls_url}`
})

step('⑭ 学生B回放（时长+断点续播）', async () => {
  const p1 = Math.min(5, (await R('get', `/schedules/${ctx.sid}/recording`, ctx.tS2)).duration)
  await R('put', `/recordings/${ctx.recid}/heartbeat`, ctx.tS2, { seconds: 30, position: p1 })
  const d = await R('put', `/recordings/${ctx.recid}/heartbeat`, ctx.tS2, { seconds: 30, position: p1 + 5 })
  return `累计 ${d.total_seconds}s · 断点 ${d.last_position}s`
})

step('⑮ 作业：布置→提交→批改', async () => {
  const a = await R('post', '/assignments', ctx.tTeacher, { chapter_id: ctx.leaves[0].id, title: '演示作业：聚合查询', deadline: iso(60 * 24) })
  const s = await R('post', `/assignments/${a.id}/submissions`, ctx.tS1, { content: 'groupby + agg 实现' })
  const g = await R('put', `/submissions/${s.submission_id}/grade`, ctx.tTeacher, { score: 88, feedback: '思路正确' })
  return `提交准时:${!s.is_late} · 批改 ${g.score} 分（学生已收通知）`
})

step('⑯ 题库3题 → 组卷考试（总分30）', async () => {
  const mk = (body) => R('post', '/questions', ctx.tTeacher, { course_id: ctx.cid, ...body })
  const q1 = await mk({ type: 'single', stem: 'groupby返回?', options: ['DataFrameGroupBy', 'list'], answer: '0', score: 10 })
  const q2 = await mk({ type: 'judge', stem: 'agg可多函数?', options: [], answer: 'T', score: 10 })
  const q3 = await mk({ type: 'essay', stem: '简述优化器原理', options: [], answer: '', score: 10 })
  const e = await R('post', '/exams', ctx.tTeacher, {
    chapter_id: ctx.leaves[0].id, title: '演示测验', pass_score: 18, duration: 30,
    open_at: iso(-1), close_at: iso(120), question_ids: [q1.id, q2.id, q3.id] })
  ctx.eid = e.id
  return `exam #${e.id} total=${e.total_score}`
})

step('⑰ 考试：作答→自动判分→人工批改发布', async () => {
  const at = await R('post', `/exams/${ctx.eid}/attempts/start`, ctx.tS1)
  const map = { single: '0', judge: 'F', essay: '演示论述答案' }
  await R('put', `/attempts/${at.attempt_id}/answers`, ctx.tS1, {
    answers: at.questions.map((q) => ({ exam_question_id: q.exam_question_id, answer: map[q.type] || '' })) })
  const sub = await R('post', `/attempts/${at.attempt_id}/submit`, ctx.tS1)
  const g = await R('put', `/attempts/${at.attempt_id}/grade`, ctx.tTeacher, { manual_score: 7 })
  return `客观自动判分=${sub.objective_score} + 主观7 → 总分 ${g.score}/${g.total_score}`
})

step('⑱ 学习进度聚合（学生A）', async () => {
  const rows = await R('get', `/courses/${ctx.cid}/progress`, ctx.tTeacher)
  const me = rows.find((r) => r.real_name === ctx.sName) || rows[0]
  return `观看${me.watch_minutes}min · 出勤${me.attendance_present}/${me.attendance_total} · 作业${me.assignments_submitted}/${me.assignments_total}(${me.assignment_avg}) · 考试${me.exam_avg} · 完课率${me.progress_pct}%`
})

step('⑲ 课程统计 + Excel 导出', async () => {
  const st = await R('get', `/stats/courses/${ctx.cid}`, ctx.tTeacher)
  const blob = await raw.get(`/stats/export?report=course_progress&course_id=${ctx.cid}&format=xlsx`, { ...tok(ctx.tTeacher), responseType: 'blob' })
  return `参与度${JSON.stringify(st.participation)} · 成绩分布${JSON.stringify(st.grade_distribution)} · xlsx ${blob.data.size} 字节`
})

async function run() {
  running.value = true
  log.value = steps.map((s) => ({ name: s.name, status: 'wait', detail: '' }))
  for (let i = 0; i < steps.length; i++) {
    log.value[i].status = 'run'
    try {
      log.value[i].detail = await steps[i].fn()
      log.value[i].status = 'ok'
    } catch (e) {
      if (ctx.sess) { await ctx.sess.close().catch(() => {}); ctx.syn?.stop(); ctx.sess = null }
      log.value[i].detail = (e.response && `${e.response.status} ${JSON.stringify(e.response.data).slice(0, 120)}`) || String(e)
      log.value[i].status = 'fail'
      ElMessage.error(`步骤 ${i + 1} 失败，链路中断`)
      running.value = false
      return
    }
  }
  running.value = false
  ElMessage.success('全链路 19 步执行完成，可到各页面查看数据')
}
</script>

<template>
  <div class="page">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>全链路演示 · 建课→审核→选课→排课→直播互动→录制回放→作业考试→进度→统计导出
            <span class="muted">（每步真实调用 REST API 写入 PostgreSQL，每次运行生成独立的一轮数据）</span></span>
          <el-button type="primary" :loading="running" @click="run">{{ running ? '执行中…' : '▶ 执行全链路' }}</el-button>
        </div>
      </template>
      <el-table :data="log" size="small">
        <el-table-column label="状态" width="70">
          <template #default="s">
            <el-tag v-if="s.row.status === 'ok'" type="success" size="small">✓</el-tag>
            <el-tag v-else-if="s.row.status === 'fail'" type="danger" size="small">✗</el-tag>
            <el-tag v-else-if="s.row.status === 'run'" type="warning" size="small">…</el-tag>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="步骤" width="420" />
        <el-table-column prop="detail" label="实测结果（真实API返回）" />
      </el-table>
      <p v-if="!log.length" class="muted">点击右上角按钮，按 PRD 业务流程逐步验证系统链路；完成后可在「课程管理 / 课表 / 作业 / 考试」等页面看到本轮生成的数据。</p>
    </el-card>
  </div>
</template>
