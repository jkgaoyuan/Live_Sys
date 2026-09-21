<script setup>
import { ref, onMounted, computed } from 'vue'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'

const role = computed(() => auth.user.role)
const mine = ref([])          // student rows
const tList = ref([])        // teacher assignments
const courses = ref([]); const chapters = ref([]); const bank = ref([])
const showCreate = ref(false)
const aForm = ref({ course_id: null, chapter_id: null, title: '', description: '', deadline: '', question_ids: [] })
const submitDlg = ref(null)  // { aid, title, questions, answers:{}, content }
const drawer = ref(null)     // { id, title, subs, missing, questions }

async function load() {
  if (role.value === 'student') { mine.value = await http.get('/assignments/me'); return }
  tList.value = await http.get('/assignments')
  courses.value = (await http.get('/courses')).filter((c) => c.status === 'online')
}
onMounted(load)

async function pickCourse(id) {
  aForm.value.chapter_id = null
  aForm.value.question_ids = []
  const d = await http.get(`/courses/${id}`)
  chapters.value = d.chapters.filter((c) => c.parent_id)
  bank.value = await http.get(`/courses/${id}/questions`)
}

async function createA() {
  try {
    await http.post('/assignments', { chapter_id: aForm.value.chapter_id, title: aForm.value.title,
      description: aForm.value.description, deadline: aForm.value.deadline, question_ids: aForm.value.question_ids })
    ElMessage.success('作业已发布'); showCreate.value = false; bank.value = []; aForm.value = { course_id: null, chapter_id: null, title: '', description: '', deadline: '', question_ids: [] }; load()
  } catch (e) { ElMessage.error(err(e)) }
}

function openSubmit(row) {
  const answers = {}
  for (const q of row.questions) {
    const prev = q.answered ?? ''
    answers[q.question_id] = q.type === 'multiple' && prev ? String(prev).split(',').map(Number) : prev
  }
  submitDlg.value = { aid: row.id, title: row.title, questions: row.questions, answers, content: row.last_content || '' }
}

function optValue(q, j) { return q.options.length ? String(j) : (j === 0 ? 'T' : 'F') }

async function doSubmit() {
  const unanswered = submitDlg.value.questions.filter((q) => {
    const v = submitDlg.value.answers[q.question_id]
    return Array.isArray(v) ? !v.length : !String(v ?? '').trim()
  })
  if (unanswered.length) {
    ElMessage.warning(`还有 ${unanswered.length} 道题未作答`)
    return
  }
  try {
    const answers = submitDlg.value.questions.map((q) => {
      const v = submitDlg.value.answers[q.question_id]
      return { question_id: q.question_id, answer: Array.isArray(v) ? v.join(',') : String(v ?? '') }
    })
    const d = await http.post(`/assignments/${submitDlg.value.aid}/submissions`, { content: submitDlg.value.content, answers })
    ElMessage.success(d.is_late ? '已提交（标记为补交）' : '提交成功'); submitDlg.value = null; load()
  } catch (e) { ElMessage.error(err(e)) }
}

async function openDrawer(a) {
  const d = await http.get(`/assignments/${a.id}/submissions`)
  drawer.value = { ...a, subs: d.submitted, missing: d.missing, questions: d.questions }
}

async function grade(row) {
  try {
    await http.put(`/submissions/${row.submission_id}/grade`, { score: row.score, feedback: row.feedback })
    ElMessage.success('批改完成，学生将收到通知')
    const d = await http.get(`/assignments/${drawer.value.id}/submissions`)
    drawer.value.subs = d.submitted
  } catch (e) { ElMessage.error(err(e)) }
}

const drawerTotal = computed(() => (drawer.value?.questions || []).reduce((s, q) => s + (q.score || 0), 0))

async function remind() {
  const d = await http.post(`/assignments/${drawer.value.id}/remind`)
  ElMessage.success(`已向 ${d.reminded} 名未交学生发送催交通知`)
}
</script>

<template>
  <div class="page">
    <!-- 学生视图 -->
    <el-card v-if="role === 'student'">
      <template #header>我的作业</template>
      <el-table :data="mine" size="small">
        <el-table-column prop="title" label="作业" min-width="200" />
        <el-table-column label="形式" width="90">
          <template #default="s"><el-tag size="small" :type="s.row.questions.length ? 'primary' : 'info'">{{ s.row.questions.length ? `${s.row.questions.length} 道题` : '自由作答' }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="deadline" label="截止" width="180" />
        <el-table-column label="状态" width="140">
          <template #default="s">
            <el-tag size="small" v-if="s.row.status === 'none'" type="info">未提交</el-tag>
            <el-tag size="small" v-else-if="s.row.status === 'submitted'" :type="s.row.is_late ? 'warning' : 'primary'">{{ s.row.is_late ? '已补交' : '已提交' }}</el-tag>
            <el-tag size="small" v-else type="success">已批改 {{ s.row.score }} 分</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="feedback" label="评语" min-width="140" />
        <el-table-column label="操作" width="120">
          <template #default="s">
            <el-button v-if="s.row.status !== 'graded'" size="small" type="primary"
              @click="openSubmit(s.row)">{{ s.row.status === 'none' ? '提交' : '重新提交' }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 讲师视图 -->
    <el-card v-else>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>作业管理</span>
          <el-button type="primary" size="small" @click="showCreate = true">布置作业</el-button>
        </div>
      </template>
      <el-table :data="tList" size="small">
        <el-table-column prop="id" label="#" width="46" />
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column label="题目" width="80"><template #default="s">{{ s.row.question_count || '自由' }}</template></el-table-column>
        <el-table-column prop="deadline" label="截止" width="180" />
        <el-table-column label="提交" width="100"><template #default="s">{{ s.row.submitted }}/{{ s.row.enrolled }}</template></el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="s"><el-button size="small" @click="openDrawer(s.row)">批改 / 明细</el-button></template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="布置作业" width="500px">
      <el-form label-width="70px">
        <el-form-item label="课程"><el-select v-model="aForm.course_id" style="width:100%" @change="pickCourse">
          <el-option v-for="c in courses" :key="c.id" :label="c.title" :value="c.id" /></el-select></el-form-item>
        <el-form-item label="章节"><el-select v-model="aForm.chapter_id" style="width:100%">
          <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" /></el-select></el-form-item>
        <el-form-item label="标题"><el-input v-model="aForm.title" /></el-form-item>
        <el-form-item label="题库选题">
          <el-select v-model="aForm.question_ids" multiple collapse-tags collapse-tags-tooltip style="width:100%"
            :disabled="!aForm.course_id" :placeholder="bank.length ? '从题库选择题目（可多选，留空则为自由作答）' : '该课程题库暂无题目'">
            <el-option v-for="q in bank" :key="q.id" :label="`#${q.id} [${q.type}/${q.score}分] ${q.stem.slice(0, 24)}`" :value="q.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="aForm.description" type="textarea" /></el-form-item>
        <el-form-item label="截止"><el-date-picker v-model="aForm.deadline" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="showCreate = false">取消</el-button><el-button type="primary" @click="createA">发布</el-button></template>
    </el-dialog>

    <el-dialog :model-value="!!submitDlg" title="提交作业" width="620px" @close="submitDlg = null">
      <template v-if="submitDlg">
        <p><b>{{ submitDlg.title }}</b></p>
        <template v-if="submitDlg.questions.length">
          <div v-for="(q, i) in submitDlg.questions" :key="q.question_id" style="margin-bottom:14px">
            <p><b>{{ i + 1 }}.（{{ q.type }} · {{ q.score }}分）{{ q.stem }}</b></p>
            <el-radio-group v-if="q.type === 'single' || q.type === 'judge'" v-model="submitDlg.answers[q.question_id]">
              <el-radio v-for="(o, j) in (q.options.length ? q.options : ['正确','错误'])" :key="j" :value="optValue(q, j)">{{ o }}</el-radio>
            </el-radio-group>
            <el-checkbox-group v-else-if="q.type === 'multiple'" v-model="submitDlg.answers[q.question_id]">
              <el-checkbox v-for="(o, j) in q.options" :key="j" :value="j">{{ j }}. {{ o }}</el-checkbox>
            </el-checkbox-group>
            <el-input v-else v-model="submitDlg.answers[q.question_id]" type="textarea" :rows="2" placeholder="论述题作答" />
          </div>
        </template>
        <el-input v-else v-model="submitDlg.content" type="textarea" :rows="4" placeholder="答案内容（演示附件上传省略）" />
      </template>
      <template #footer><el-button @click="submitDlg = null">取消</el-button><el-button type="primary" @click="doSubmit">提交</el-button></template>
    </el-dialog>

    <el-drawer :model-value="!!drawer" :title="drawer && drawer.title" size="640px" @close="drawer = null">
      <template v-if="drawer">
        <p class="muted">未交：{{ drawer.missing.join('、') || '无' }}</p>
        <p v-if="drawer.questions && drawer.questions.length" class="muted">
          本作业含 {{ drawer.questions.length }} 道题库题，题目总分 {{ drawerTotal }} 分；批改时请对照学生逐题作答
        </p>
        <el-button size="small" type="warning" @click="remind" :disabled="!drawer.missing.length">一键催交</el-button>
        <el-table :data="drawer.subs" size="small" style="margin-top:12px">
          <el-table-column type="expand" v-if="drawer.questions && drawer.questions.length">
            <template #default="s">
              <div style="padding:0 16px">
                <div v-for="(a, i) in s.row.answers" :key="a.question_id" style="margin-bottom:8px">
                  <p><b>{{ i + 1 }}.（{{ a.type }}）{{ a.stem }}</b></p>
                  <p>学生作答：<span :style="{ color: a.student_answer === a.std_answer ? '#67c23a' : '#e6a23c' }">{{ a.student_answer || '（未作答）' }}</span>
                    <span class="muted"> · 参考答案：{{ a.std_answer || '人工评判' }}</span></p>
                </div>
                <p v-if="s.row.content"><b>补充说明：</b>{{ s.row.content }}</p>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="real_name" label="学生" width="86" />
          <el-table-column label="状态" width="120">
            <template #default="s">
              <el-tag size="small" :type="s.row.status === 'graded' ? 'success' : (s.row.is_late ? 'warning' : 'primary')">
                {{ s.row.status === 'graded' ? '已批改' : (s.row.is_late ? '补交' : '待批改') }} v{{ s.row.version }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="评分/评语">
            <template #default="s">
              <template v-if="s.row.status === 'graded'">{{ s.row.score }} · {{ s.row.feedback }}</template>
              <div v-else style="display:flex;gap:6px">
                <el-input-number v-model="s.row.score" size="small" :min="0" :max="100" style="width:92px" />
                <el-input v-model="s.row.feedback" size="small" placeholder="评语" />
                <el-button size="small" type="primary" @click="grade(s.row)">批</el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>
  </div>
</template>
