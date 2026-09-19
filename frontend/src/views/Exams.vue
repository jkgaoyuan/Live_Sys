<script setup>
import { ref, onMounted, computed } from 'vue'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'

const role = computed(() => auth.user.role)
// 学生
const mine = ref([])
const paper = ref(null)   // { attempt_id, questions, answers:{}, deadline }
const result = ref(null)
// 讲师
const exams = ref([]); const courses = ref([])
const bank = ref([]); const bankCourse = ref(null)
const showQ = ref(false); const qForm = ref({ type: 'single', stem: '', options: '选项A\n选项B\n选项C\n选项D', answer: '0', score: 10 })
const showE = ref(false)
const eForm = ref({ course_id: null, chapter_id: null, title: '', question_ids: [], duration: 45, pass_score: 30, range: [] })
const chapters = ref([])
const drawer = ref(null)

async function load() {
  if (role.value === 'student') { mine.value = await http.get('/exams/me'); return }
  exams.value = await http.get('/exams')
  courses.value = (await http.get('/courses')).filter((c) => c.status === 'online')
}
onMounted(load)

// ---------- 学生 ----------
async function startExam(row) {
  try {
    const d = await http.post(`/exams/${row.id}/attempts/start`)
    paper.value = { attempt_id: d.attempt_id, questions: d.questions, answers: {}, deadline: d.deadline, title: row.title }
    for (const q of d.questions) {
      paper.value.answers[q.exam_question_id] = q.type === 'multiple'
        ? (q.answered ? q.answered.split(',').map(Number) : [])
        : (q.answered ?? '')
    }
  } catch (e) { ElMessage.error(err(e)) }
}

async function submitPaper() {
  const answers = Object.entries(paper.value.answers)
    .filter(([, v]) => Array.isArray(v) ? v.length : String(v).length)
    .map(([k, v]) => ({ exam_question_id: Number(k), answer: Array.isArray(v) ? v.join(',') : String(v) }))
  try {
    await http.put(`/attempts/${paper.value.attempt_id}/answers`, { answers, switch_event: false })
    result.value = await http.post(`/attempts/${paper.value.attempt_id}/submit`)
    paper.value = null
    load()
  } catch (e) { ElMessage.error(err(e)) }
}

// ---------- 讲师 ----------
async function pickBank(id) { bankCourse.value = id; bank.value = await http.get(`/courses/${id}/questions`) }
async function addQ() {
  try {
    const opts = qForm.value.type === 'single' || qForm.value.type === 'multiple'
      ? qForm.value.options.split('\n').filter(Boolean) : []
    await http.post('/questions', { course_id: bankCourse.value, type: qForm.value.type, stem: qForm.value.stem,
      options: opts, answer: qForm.value.answer, score: qForm.value.score })
    ElMessage.success('已入库'); showQ.value = false; pickBank(bankCourse.value)
  } catch (e) { ElMessage.error(err(e)) }
}

async function pickECourse(id) {
  eForm.value.chapter_id = null; eForm.value.question_ids = []
  const d = await http.get(`/courses/${id}`)
  chapters.value = d.chapters.filter((c) => c.parent_id)
  bank.value = await http.get(`/courses/${id}/questions`)
}

async function createExam() {
  try {
    await http.post('/exams', { chapter_id: eForm.value.chapter_id, title: eForm.value.title,
      question_ids: eForm.value.question_ids, duration: eForm.value.duration, pass_score: eForm.value.pass_score,
      open_at: eForm.value.range[0], close_at: eForm.value.range[1] })
    ElMessage.success('考试已创建'); showE.value = false; load()
  } catch (e) { ElMessage.error(err(e)) }
}

async function openDrawer(row) {
  drawer.value = { ...row, attempts: await http.get(`/exams/${row.id}/attempts`) }
}

function optValue(q, j) {
  return q.options.length ? String(j) : (j === 0 ? 'T' : 'F')
}
async function gradeAttempt(a) {
  try {
    const d = await http.put(`/attempts/${a.attempt_id}/grade`, { manual_score: a.manual_score })
    ElMessage.success(`已发布成绩：${d.score}/${d.total_score}`)
    openDrawer({ id: drawer.value.id })
    load()
  } catch (e) { ElMessage.error(err(e)) }
}
</script>

<template>
  <div class="page">
    <!-- 学生 -->
    <el-card v-if="role === 'student'">
      <template #header>我的考试</template>
      <el-alert v-if="result" type="success" :closable="false" style="margin-bottom:12px"
        :title="result.status === 'graded' ? `已判分：${result.total}/${result.total_score}` : `客观题得分 ${result.objective_score}，主观题等待讲师批改`" />
      <el-table :data="mine" size="small">
        <el-table-column prop="title" label="考试" min-width="180" />
        <el-table-column label="开放窗口" width="300"><template #default="s">{{ s.row.open_at.replace('T',' ').slice(0,16) }} ~ {{ s.row.close_at.replace('T',' ').slice(0,16) }}</template></el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="s">
            <el-tag size="small" :type="s.row.attempt_status === 'graded' ? 'success' : (s.row.attempt_status === 'none' ? 'info' : 'warning')">
              {{ { none: '未参加', taking: '进行中', submitted: '待批改', graded: '已判分' }[s.row.attempt_status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="成绩" width="100"><template #default="s">{{ s.row.score ?? '-' }}</template></el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="s">
            <el-button v-if="['none','taking'].includes(s.row.attempt_status)" size="small" type="primary" @click="startExam(s.row)">
              {{ s.row.attempt_status === 'taking' ? '继续作答' : '开始考试' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 讲师 -->
    <template v-else>
      <el-card class="card-gap">
        <template #header>
          <div style="display:flex;justify-content:space-between">
            <span>考试管理</span>
            <span>
              <el-select v-model="bankCourse" size="small" style="width:170px" placeholder="题库课程" @change="pickBank">
                <el-option v-for="c in courses" :key="c.id" :label="c.title" :value="c.id" /></el-select>
              <el-button size="small" style="margin-left:8px" :disabled="!bankCourse" @click="showQ = true">录入题目</el-button>
              <el-button size="small" type="primary" style="margin-left:8px" @click="showE = true">创建考试</el-button>
            </span>
          </div>
        </template>
        <el-table :data="exams" size="small">
          <el-table-column prop="id" label="#" width="46" />
          <el-table-column prop="title" label="考试" min-width="150" />
          <el-table-column prop="total_score" label="总分" width="70" />
          <el-table-column prop="pass_score" label="及格" width="70" />
          <el-table-column label="答卷" width="130"><template #default="s">已考 {{ s.row.attempts }} · 待批改 {{ s.row.pending_manual }}</template></el-table-column>
          <el-table-column label="操作" width="110"><template #default="s"><el-button size="small" @click="openDrawer(s.row)">批改</el-button></template></el-table-column>
        </el-table>
      </el-card>
      <el-card v-if="bankCourse">
        <template #header>题库（课程 #{{ bankCourse }}，共 {{ bank.length }} 题）</template>
        <el-table :data="bank" size="small">
          <el-table-column prop="id" label="#" width="46" />
          <el-table-column prop="type" label="题型" width="90" />
          <el-table-column prop="stem" label="题干" min-width="220" />
          <el-table-column prop="score" label="分值" width="60" />
        </el-table>
      </el-card>
    </template>

    <!-- 学生答卷对话框 -->
    <el-dialog :model-value="!!paper" :title="paper && paper.title" width="640px" :close-on-click-modal="false">
      <template v-if="paper">
        <div v-for="(q, i) in paper.questions" :key="q.exam_question_id" style="margin-bottom:14px">
          <p><b>{{ i + 1 }}.（{{ q.type }} · {{ q.score }}分）{{ q.stem }}</b></p>
          <el-radio-group v-if="q.type === 'single' || q.type === 'judge'" v-model="paper.answers[q.exam_question_id]">
            <el-radio v-for="(o, j) in (q.options.length ? q.options : ['正确','错误'])" :key="j" :value="optValue(q, j)">{{ o }}</el-radio>
          </el-radio-group>
          <el-checkbox-group v-else-if="q.type === 'multiple'" v-model="paper.answers[q.exam_question_id]">
            <el-checkbox v-for="(o, j) in q.options" :key="j" :value="j">{{ j }}. {{ o }}</el-checkbox>
          </el-checkbox-group>
          <el-input v-else v-model="paper.answers[q.exam_question_id]" type="textarea" :rows="2" placeholder="论述题作答" />
        </div>
      </template>
      <template #footer><el-button @click="paper = null">暂存退出</el-button><el-button type="primary" @click="submitPaper">交卷</el-button></template>
    </el-dialog>

    <!-- 录题 -->
    <el-dialog v-model="showQ" title="录入题目" width="500px">
      <el-form label-width="60px">
        <el-form-item label="题型"><el-select v-model="qForm.type" style="width:100%">
          <el-option v-for="t in ['single','multiple','judge','essay']" :key="t" :label="t" :value="t" /></el-select></el-form-item>
        <el-form-item label="题干"><el-input v-model="qForm.stem" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="选项" v-if="['single','multiple'].includes(qForm.type)">
          <el-input v-model="qForm.options" type="textarea" :rows="4" placeholder="每行一个选项" /></el-form-item>
        <el-form-item label="答案">
          <el-input v-model="qForm.answer" placeholder="单选/判断: 索引或T/F；多选逗号分隔如 0,2；论述可留空" /></el-form-item>
        <el-form-item label="分值"><el-input-number v-model="qForm.score" :min="1" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="showQ = false">取消</el-button><el-button type="primary" @click="addQ">保存</el-button></template>
    </el-dialog>

    <!-- 创建考试 -->
    <el-dialog v-model="showE" title="创建考试（从题库选题组卷）" width="540px">
      <el-form label-width="70px">
        <el-form-item label="课程"><el-select v-model="eForm.course_id" style="width:100%" @change="pickECourse">
          <el-option v-for="c in courses" :key="c.id" :label="c.title" :value="c.id" /></el-select></el-form-item>
        <el-form-item label="章节"><el-select v-model="eForm.chapter_id" style="width:100%">
          <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" /></el-select></el-form-item>
        <el-form-item label="标题"><el-input v-model="eForm.title" /></el-form-item>
        <el-form-item label="题目">
          <el-select v-model="eForm.question_ids" multiple style="width:100%" placeholder="先选择题库题目">
            <el-option v-for="q in bank" :key="q.id" :label="`#${q.id} [${q.type}/${q.score}分] ${q.stem.slice(0, 24)}`" :value="q.id" /></el-select>
        </el-form-item>
        <el-form-item label="窗口"><el-date-picker v-model="eForm.range" type="datetimerange" style="width:100%" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
        <el-form-item label="时长">
          <el-input-number v-model="eForm.duration" :min="5" /><span class="muted" style="margin-left:8px">分钟 · 及格分</span>
          <el-input-number v-model="eForm.pass_score" :min="1" style="margin-left:8px" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="showE = false">取消</el-button><el-button type="primary" @click="createExam">创建</el-button></template>
    </el-dialog>

    <!-- 答卷批改 -->
    <el-drawer :model-value="!!drawer" :title="drawer && drawer.title" size="520px" @close="drawer = null">
      <el-table v-if="drawer" :data="drawer.attempts" size="small">
        <el-table-column prop="student" label="学生" width="86" />
        <el-table-column prop="switch_count" label="切屏" width="60" />
        <el-table-column label="状态/成绩" min-width="200">
          <template #default="s">
            <template v-if="s.row.status === 'graded'"><el-tag size="small" type="success">{{ s.row.score }} 分</el-tag></template>
            <div v-else-if="s.row.status === 'submitted'" style="display:flex;gap:6px">
              <el-input-number v-model="s.row.manual_score" size="small" :min="0" :max="drawer.total_score" style="width:100px" />
              <el-button size="small" type="primary" @click="gradeAttempt(s.row)">批改发布</el-button>
            </div>
            <el-tag v-else size="small" type="warning">作答中</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>
