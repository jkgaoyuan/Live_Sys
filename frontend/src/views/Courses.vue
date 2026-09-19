<script setup>
import { ref, onMounted, computed } from 'vue'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage, ElMessageBox } from 'element-plus'

const role = computed(() => auth.user.role)
const list = ref([])
const classes = ref([])
const detail = ref(null)
const showCreate = ref(false)
const showEnroll = ref(null)
const form = ref({ title: '', intro: '', audience: '', chapters: '第一章 导论：课程介绍、学习方法\n第二章 进阶：案例实战' })

async function load() { list.value = await http.get('/courses') }
onMounted(async () => {
  await load()
  if (['admin', 'teacher'].includes(role.value)) classes.value = await http.get('/classes')
})

function parseChapters(text) {
  return text.split('\n').map((l) => l.trim()).filter(Boolean).map((line, i) => {
    const [title, subs] = line.split(/[：:]/)
    return { title: title.trim(), sort: i,
      children: (subs || '').split(/[、,，;]/).map((s) => s.trim()).filter(Boolean).map((t, j) => ({ title: t, sort: j })) }
  })
}

async function createCourse() {
  try {
    await http.post('/courses', { ...form.value, cover_url: '/img/demo.png', chapters: parseChapters(form.value.chapters) })
    ElMessage.success('课程已创建（草稿）')
    showCreate.value = false
    load()
  } catch (e) { ElMessage.error(err(e)) }
}

async function submitReview(c) {
  try { await http.post(`/courses/${c.id}/submit-review`); ElMessage.success('已提交审核'); load() }
  catch (e) { ElMessage.error(err(e)) }
}

async function review(c, decision) {
  try { await http.put(`/courses/${c.id}/review`, { decision }); ElMessage.success(decision === 'approve' ? '审核通过' : '已驳回'); load() }
  catch (e) { ElMessage.error(err(e)) }
}

async function openDetail(c) {
  try { detail.value = await http.get(`/courses/${c.id}`) } catch (e) { ElMessage.error(err(e)) }
}

async function enroll() {
  try {
    const d = await http.post(`/courses/${showEnroll.value.id}/enroll`, { class_id: showEnroll.value.enrollClass })
    ElMessage.success(`已导入 ${d.enrolled} 名学生`); showEnroll.value = null; load()
  } catch (e) { ElMessage.error(err(e)) }
}

async function remove(c) {
  await ElMessageBox.confirm(`确认删除课程 #${c.id}？`, '警告', { type: 'warning' })
  ElMessage.info('演示环境未开放删除接口，保留数据完整性')
}

const STATUS = { draft: ['草稿', 'info'], pending: ['待审核', 'warning'], online: ['已上线', 'success'], rejected: ['已驳回', 'danger'], offline: ['已下架', 'info'] }
</script>

<template>
  <div class="page">
    <el-card>
      <template #header>
        <div style="display:flex; justify-content: space-between; align-items:center">
          <span>课程列表<span class="muted" style="margin-left:8px">数据范围由后端按角色过滤</span></span>
          <el-button v-if="role === 'teacher'" type="primary" size="small" @click="showCreate = true">新建课程</el-button>
        </div>
      </template>
      <el-table :data="list" size="small">
        <el-table-column prop="id" label="#" width="50" />
        <el-table-column prop="title" label="课程名" min-width="180" />
        <el-table-column prop="audience" label="适用人群" width="130" />
        <el-table-column prop="chapter_count" label="章节" width="70" />
        <el-table-column label="状态" width="90">
          <template #default="s"><el-tag :type="STATUS[s.row.status][1]" size="small">{{ STATUS[s.row.status][0] }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" min-width="280">
          <template #default="s">
            <el-button size="small" @click="openDetail(s.row)">大纲</el-button>
            <template v-if="role === 'teacher' && s.row.teacher_id === auth.user.id">
              <el-button v-if="['draft','rejected'].includes(s.row.status)" size="small" type="warning" @click="submitReview(s.row)">提交审核</el-button>
              <el-button v-if="s.row.status === 'online'" size="small" type="success"
                @click="showEnroll = { ...s.row, enrollClass: classes[0] && classes[0].id }">按班级选课</el-button>
            </template>
            <template v-if="role === 'admin' && s.row.status === 'pending'">
              <el-button size="small" type="success" @click="review(s.row, 'approve')">通过</el-button>
              <el-button size="small" type="danger" @click="review(s.row, 'reject')">驳回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="新建课程" width="560px">
      <el-form label-width="80px">
        <el-form-item label="课程名"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="简介"><el-input v-model="form.intro" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="适用人群"><el-input v-model="form.audience" /></el-form-item>
        <el-form-item label="大纲">
          <el-input v-model="form.chapters" type="textarea" :rows="5"
            placeholder="每行一个章；用冒号分隔小节，顿号分隔多个小节" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="showCreate = false">取消</el-button><el-button type="primary" @click="createCourse">创建</el-button></template>
    </el-dialog>

    <el-dialog :model-value="!!detail" title="课程大纲" width="480px" @close="detail = null">
      <template v-if="detail">
        <h4 style="margin-top:0">{{ detail.title }} <span class="muted">讲师：{{ detail.teacher_name }}</span></h4>
        <el-tree :data="detail.chapters.filter(c => !c.parent_id).map(c => ({ label: c.title, children: detail.chapters.filter(s => s.parent_id === c.id).map(s => ({ label: s.title })) }))" />
      </template>
    </el-dialog>

    <el-dialog :model-value="!!showEnroll" title="按班级批量选课" width="420px" @close="showEnroll = null">
      <template v-if="showEnroll">
        <p>{{ showEnroll.title }}</p>
        <el-select v-model="showEnroll.enrollClass" style="width:100%">
          <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <p class="muted">将把该班级全部学生导入课程（已选课自动跳过）</p>
      </template>
      <template #footer><el-button @click="showEnroll = null">取消</el-button><el-button type="primary" @click="enroll">导入</el-button></template>
    </el-dialog>
  </div>
</template>
