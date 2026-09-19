<script setup>
import { ref, onMounted, computed } from 'vue'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'

const router = useRouter()
const role = computed(() => auth.user.role)
const rows = ref([])
const courses = ref([])
const chapters = ref([])
const showCreate = ref(false)
const form = ref({ course_id: null, chapter_id: null, range: [], mode: 'screen' })

const ST = { planned: ['已排课', 'info'], living: ['直播中', 'danger'], finished: ['已结束', 'success'], canceled: ['已取消', 'info'] }

async function load() { rows.value = await http.get('/schedules/timetable') }

onMounted(async () => {
  await load()
  if (role.value === 'teacher') courses.value = (await http.get('/courses')).filter((c) => c.status === 'online')
})

async function pickCourse(id) {
  form.value.chapter_id = null
  const d = await http.get(`/courses/${id}`)
  chapters.value = d.chapters.filter((c) => c.parent_id)
}

async function create() {
  try {
    await http.post('/schedules', {
      chapter_id: form.value.chapter_id, mode: form.value.mode,
      start_at: form.value.range[0], end_at: form.value.range[1],
    })
    ElMessage.success('排课成功'); showCreate.value = false; load()
  } catch (e) { ElMessage.error(err(e)) }
}

function fmt(s) { return (s || '').replace('T', ' ').slice(0, 16) }
</script>

<template>
  <div class="page">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>{{ role === 'student' ? '我的课表' : '直播排课表' }}<span class="muted" style="margin-left:8px">按角色数据范围返回</span></span>
          <el-button v-if="role === 'teacher'" type="primary" size="small" @click="showCreate = true">新增排课</el-button>
        </div>
      </template>
      <el-table :data="rows" size="small">
        <el-table-column prop="id" label="#" width="46" />
        <el-table-column prop="title" label="直播主题" min-width="160" />
        <el-table-column label="时间" width="230"><template #default="s">{{ fmt(s.row.start_at) }} ~ {{ fmt(s.row.end_at) }}</template></el-table-column>
        <el-table-column prop="mode" label="形式" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="s"><el-tag :type="ST[s.row.status][1]" size="small">{{ ST[s.row.status][0] }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="s">
            <el-button size="small" type="primary" plain @click="router.push(`/room/${s.row.id}`)">直播间</el-button>
            <el-button v-if="s.row.status === 'finished'" size="small" @click="router.push(`/replay/${s.row.id}`)">回放</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="新增排课" width="480px">
      <el-form label-width="80px">
        <el-form-item label="课程">
          <el-select v-model="form.course_id" style="width:100%" @change="pickCourse">
            <el-option v-for="c in courses" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="章节">
          <el-select v-model="form.chapter_id" style="width:100%">
            <el-option v-for="c in chapters" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间">
          <el-date-picker v-model="form.range" type="datetimerange" style="width:100%" value-format="YYYY-MM-DDTHH:mm:ss" />
        </el-form-item>
        <el-form-item label="形式">
          <el-radio-group v-model="form.mode"><el-radio value="video">音视频</el-radio><el-radio value="screen">屏幕共享</el-radio><el-radio value="whiteboard">白板</el-radio></el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="showCreate = false">取消</el-button><el-button type="primary" @click="create">排课</el-button></template>
    </el-dialog>
  </div>
</template>
