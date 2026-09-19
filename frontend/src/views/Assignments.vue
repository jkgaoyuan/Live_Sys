<script setup>
import { ref, onMounted, computed } from 'vue'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'

const role = computed(() => auth.user.role)
const mine = ref([])          // student rows
const tList = ref([])        // teacher assignments
const courses = ref([]); const chapters = ref([])
const showCreate = ref(false)
const aForm = ref({ course_id: null, chapter_id: null, title: '', description: '', deadline: '' })
const submitDlg = ref(null)  // { aid, title }
const drawer = ref(null)     // { id, title, subs, missing }

async function load() {
  if (role.value === 'student') { mine.value = await http.get('/assignments/me'); return }
  tList.value = await http.get('/assignments')
  courses.value = (await http.get('/courses')).filter((c) => c.status === 'online')
}
onMounted(load)

async function pickCourse(id) {
  aForm.value.chapter_id = null
  chapters.value = (await http.get(`/courses/${id}`)).chapters.filter((c) => c.parent_id)
}

async function createA() {
  try {
    await http.post('/assignments', { chapter_id: aForm.value.chapter_id, title: aForm.value.title,
      description: aForm.value.description, deadline: aForm.value.deadline })
    ElMessage.success('作业已发布'); showCreate.value = false; load()
  } catch (e) { ElMessage.error(err(e)) }
}

async function doSubmit() {
  try {
    const d = await http.post(`/assignments/${submitDlg.value.aid}/submissions`, { content: submitDlg.value.content })
    ElMessage.success(d.is_late ? '已提交（标记为补交）' : '提交成功'); submitDlg.value = null; load()
  } catch (e) { ElMessage.error(err(e)) }
}

async function openDrawer(a) {
  const d = await http.get(`/assignments/${a.id}/submissions`)
  drawer.value = { ...a, subs: d.submitted, missing: d.missing }
}

async function grade(row) {
  try {
    await http.put(`/submissions/${row.submission_id}/grade`, { score: row.score, feedback: row.feedback })
    ElMessage.success('批改完成，学生将收到通知')
    drawer.value.subs = await http.get(`/assignments/${drawer.value.id}/submissions`).then((d) => d.submitted)
  } catch (e) { ElMessage.error(err(e)) }
}

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
              @click="submitDlg = { aid: s.row.id, title: s.row.title, content: '' }">{{ s.row.status === 'none' ? '提交' : '重新提交' }}</el-button>
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
        <el-form-item label="说明"><el-input v-model="aForm.description" type="textarea" /></el-form-item>
        <el-form-item label="截止"><el-date-picker v-model="aForm.deadline" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="showCreate = false">取消</el-button><el-button type="primary" @click="createA">发布</el-button></template>
    </el-dialog>

    <el-dialog :model-value="!!submitDlg" title="提交作业" width="480px" @close="submitDlg = null">
      <template v-if="submitDlg">
        <p><b>{{ submitDlg.title }}</b></p>
        <el-input v-model="submitDlg.content" type="textarea" :rows="4" placeholder="答案内容（演示附件上传省略）" />
      </template>
      <template #footer><el-button @click="submitDlg = null">取消</el-button><el-button type="primary" @click="doSubmit">提交</el-button></template>
    </el-dialog>

    <el-drawer :model-value="!!drawer" :title="drawer && drawer.title" size="560px" @close="drawer = null">
      <template v-if="drawer">
        <p class="muted">未交：{{ drawer.missing.join('、') || '无' }}</p>
        <el-button size="small" type="warning" @click="remind" :disabled="!drawer.missing.length">一键催交</el-button>
        <el-table :data="drawer.subs" size="small" style="margin-top:12px">
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
