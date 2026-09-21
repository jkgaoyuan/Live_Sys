<script setup>
import { ref, onMounted, computed } from 'vue'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage, ElMessageBox } from 'element-plus'

const role = computed(() => auth.user.role)
const list = ref([])
const classes = ref([])
const teachers = ref([])
const detail = ref(null)
const showCreate = ref(false)
const showEnroll = ref(null)
const uploading = ref(false)
const form = ref({ title: '', intro: '', audience: '', chapters: '第一章 导论：课程介绍、学习方法\n第二章 进阶：案例实战',
  cover_url: '', teacher_id: null })

async function load() { list.value = await http.get('/courses') }
onMounted(async () => {
  await load()
  if (['admin', 'teacher'].includes(role.value)) classes.value = await http.get('/classes')
})

async function openCreate() {
  form.value = { title: '', intro: '', audience: '', chapters: form.value.chapters, cover_url: '', teacher_id: null }
  if (role.value === 'admin') {
    try { teachers.value = await http.get('/teachers') } catch (e) { ElMessage.error(err(e)) }
  }
  showCreate.value = true
}

async function uploadCover(opt) {
  const fd = new FormData()
  fd.append('file', opt.file)
  uploading.value = true
  try {
    const d = await http.post('/uploads', fd)
    form.value.cover_url = d.url
    ElMessage.success('封面已上传')
  } catch (e) { ElMessage.error(err(e)) } finally { uploading.value = false }
}

function parseChapters(text) {
  return text.split('\n').map((l) => l.trim()).filter(Boolean).map((line, i) => {
    const [title, subs] = line.split(/[：:]/)
    return { title: title.trim(), sort: i,
      children: (subs || '').split(/[、,，;]/).map((s) => s.trim()).filter(Boolean).map((t, j) => ({ title: t, sort: j })) }
  })
}

async function createCourse() {
  if (role.value === 'admin' && !form.value.teacher_id) { ElMessage.warning('请选择讲师'); return }
  try {
    await http.post('/courses', {
      title: form.value.title, intro: form.value.intro, audience: form.value.audience,
      cover_url: form.value.cover_url, teacher_id: form.value.teacher_id,
      chapters: parseChapters(form.value.chapters) })
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

const canEditOutline = computed(() => detail.value &&
  (role.value === 'admin' || detail.value.teacher_id === auth.user.id))
const topChapters = computed(() => detail.value ? detail.value.chapters.filter((c) => !c.parent_id) : [])
const subsOf = (pid) => (detail.value ? detail.value.chapters.filter((c) => c.parent_id === pid) : [])

async function reloadDetail() {
  detail.value = await http.get(`/courses/${detail.value.id}`)
  load()
}

const titleValidator = (v) => (!v || !v.trim() ? '标题不能为空' : v.trim().length > 64 ? '不能超过 64 个字符' : true)

async function addChapter(parent) {
  try {
    const { value } = await ElMessageBox.prompt('标题', parent ? `为「${parent.title}」添加小节` : '添加章', {
      inputValidator: titleValidator, confirmButtonText: '添加', cancelButtonText: '取消' })
    await http.post(`/courses/${detail.value.id}/chapters`, { title: value.trim(), parent_id: parent ? parent.id : null })
    ElMessage.success('章节已添加'); reloadDetail()
  } catch (e) { if (e?.response) ElMessage.error(err(e)) }
}

async function renameChapter(ch) {
  try {
    const { value } = await ElMessageBox.prompt('新标题', '重命名章节', {
      inputValue: ch.title, inputValidator: titleValidator, confirmButtonText: '保存', cancelButtonText: '取消' })
    await http.put(`/chapters/${ch.id}`, { title: value.trim() })
    ElMessage.success('已重命名'); reloadDetail()
  } catch (e) { if (e?.response) ElMessage.error(err(e)) }
}

async function removeChapter(ch) {
  try {
    await ElMessageBox.confirm(`确定删除${ch.parent_id ? '小节' : '章'}「${ch.title}」？`, '删除章节', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await http.delete(`/chapters/${ch.id}`)
    ElMessage.success('章节已删除'); reloadDetail()
  } catch (e) { if (e?.response) ElMessage.error(err(e)) }
}

async function enroll() {
  if (!showEnroll.value.enrollClasses?.length) { ElMessage.warning('请至少选择一个班级'); return }
  try {
    const d = await http.post(`/courses/${showEnroll.value.id}/enroll`, { class_ids: showEnroll.value.enrollClasses })
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
          <el-button v-if="['teacher', 'admin'].includes(role)" type="primary" size="small" @click="openCreate">新建课程</el-button>
        </div>
      </template>
      <el-table :data="list" size="small">
        <el-table-column prop="id" label="#" width="50" />
        <el-table-column label="封面" width="90">
          <template #default="s">
            <img v-if="s.row.cover_url" :src="s.row.cover_url" class="cover-thumb" alt="封面" />
            <span v-else class="muted">无</span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="课程名" min-width="160" />
        <el-table-column prop="teacher_name" label="讲师" width="100" />
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
                @click="showEnroll = { ...s.row, enrollClasses: [] }">按班级选课</el-button>
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
        <el-form-item label="课程封面">
          <div style="display:flex;align-items:center;gap:12px">
            <el-upload accept="image/png,image/jpeg,image/webp,image/gif" :show-file-list="false" :http-request="uploadCover">
              <el-button size="small" :loading="uploading">上传封面</el-button>
            </el-upload>
            <template v-if="form.cover_url">
              <img :src="form.cover_url" class="cover-thumb" alt="预览" />
              <el-button size="small" text type="danger" @click="form.cover_url = ''">移除</el-button>
            </template>
            <span v-else class="muted">未设置（支持 png/jpg/webp/gif，≤2MB）</span>
          </div>
        </el-form-item>
        <el-form-item v-if="role === 'admin'" label="讲师">
          <el-select v-model="form.teacher_id" placeholder="选择授课讲师" style="width:100%">
            <el-option v-for="t in teachers" :key="t.id" :label="`${t.real_name}（${t.username}）`" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="讲师">
          <el-input :model-value="auth.user.real_name + '（本人）'" disabled />
        </el-form-item>
        <el-form-item label="大纲">
          <el-input v-model="form.chapters" type="textarea" :rows="5"
            placeholder="每行一个章；用冒号分隔小节，顿号分隔多个小节" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="showCreate = false">取消</el-button><el-button type="primary" @click="createCourse">创建</el-button></template>
    </el-dialog>

    <el-dialog :model-value="!!detail" title="课程大纲" width="560px" @close="detail = null">
      <template v-if="detail">
        <h4 style="margin-top:0">{{ detail.title }} <span class="muted">讲师：{{ detail.teacher_name }}</span></h4>
        <img v-if="detail.cover_url" :src="detail.cover_url"
          style="width:100%;max-height:170px;object-fit:cover;border-radius:6px;margin-bottom:10px" alt="课程封面" />
        <div v-for="ch in topChapters" :key="ch.id" class="ch-line">
          <div class="ch-row">
            <b>{{ ch.title }}</b>
            <span v-if="canEditOutline" class="ch-ops">
              <el-button size="small" text type="primary" @click="addChapter(ch)">加小节</el-button>
              <el-button size="small" text @click="renameChapter(ch)">改名</el-button>
              <el-button size="small" text type="danger" @click="removeChapter(ch)">删除</el-button>
            </span>
          </div>
          <div v-for="s in subsOf(ch.id)" :key="s.id" class="sub-line">
            <span>└ {{ s.title }}</span>
            <span v-if="canEditOutline" class="ch-ops">
              <el-button size="small" text @click="renameChapter(s)">改名</el-button>
              <el-button size="small" text type="danger" @click="removeChapter(s)">删除</el-button>
            </span>
          </div>
        </div>
        <p v-if="!topChapters.length" class="muted">暂无章节</p>
        <el-button v-if="canEditOutline" size="small" style="margin-top:8px" @click="addChapter(null)">＋ 添加章</el-button>
        <p v-if="canEditOutline" class="muted" style="margin-top:8px">已关联排课 / 作业 / 考试的章节不可删除，会提示原因</p>
      </template>
    </el-dialog>

    <el-dialog :model-value="!!showEnroll" title="按班级批量选课" width="460px" @close="showEnroll = null">
      <template v-if="showEnroll">
        <p>{{ showEnroll.title }}</p>
        <el-select v-model="showEnroll.enrollClasses" multiple collapse-tags collapse-tags-tooltip :multiple-limit="5" placeholder="可多选班级" style="width:100%">
          <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <p class="muted">将把所选班级的全部学生导入课程（已选课自动跳过，最多选 5 个班）</p>
      </template>
      <template #footer><el-button @click="showEnroll = null">取消</el-button><el-button type="primary" @click="enroll">导入</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.cover-thumb {
  width: 72px;
  height: 45px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid var(--el-border-color);
  display: block;
}
.ch-row { display: flex; justify-content: space-between; align-items: center; }
.sub-line { display: flex; justify-content: space-between; align-items: center; color: var(--el-text-color-regular); padding-left: 18px; }
.ch-ops { flex-shrink: 0; }
.ch-line { margin-bottom: 6px; }
</style>
