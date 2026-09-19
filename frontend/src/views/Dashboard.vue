<script setup>
import { ref, onMounted, computed } from 'vue'
import { http, download, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'
import EChart from '../components/EChart.vue'

const role = computed(() => auth.user.role)
const progress = ref([])          // student
const courses = ref([]); const curCourse = ref(null); const stats = ref(null)  // teacher
const classes = ref([]); const clsRows = ref(null)   // head_teacher
const overview = ref(null); const exportLogs = ref([]) // admin

onMounted(async () => {
  try {
    if (role.value === 'student') progress.value = await http.get('/me/progress')
    if (role.value === 'teacher') {
      courses.value = (await http.get('/courses')).filter((c) => c.status === 'online')
      if (courses.value.length) pickCourse(courses.value[0].id)
    }
    if (role.value === 'head_teacher') {
      classes.value = (await http.get('/classes')).filter((c) => c.head_teacher_id === auth.user.id)
      if (classes.value.length) pickClass(classes.value[0].id)
    }
    if (role.value === 'admin') {
      overview.value = await http.get('/stats/overview')
      exportLogs.value = await http.get('/stats/exports')
    }
  } catch (e) { ElMessage.error(err(e)) }
})

async function pickCourse(id) {
  curCourse.value = id
  stats.value = await http.get(`/stats/courses/${id}`)
}

async function pickClass(id) {
  clsRows.value = await http.get(`/classes/${id}/progress`)
}

function exportData(format) {
  download('/stats/export',
    { report: 'course_progress', course_id: curCourse.value, format },
    `course_${curCourse.value}.${format}`)
}

const gradeOption = computed(() => {
  if (!stats.value) return null
  const d = stats.value.grade_distribution
  return {
    title: { text: '成绩分布（作业/考试均分分段）', left: 'center', textStyle: { fontSize: 13 } },
    xAxis: { type: 'category', data: Object.keys(d) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', data: Object.values(d), itemStyle: { color: '#409eff' }, label: { show: true } }],
  }
})
const partOption = computed(() => {
  if (!stats.value) return null
  const p = stats.value.participation
  return {
    title: { text: '课堂参与度构成', left: 'center', textStyle: { fontSize: 13 } },
    tooltip: {}, legend: { bottom: 0 },
    series: [{ type: 'pie', radius: ['35%', '60%'], data: [
      { name: '弹幕', value: p.danmaku }, { name: '提问', value: p.question },
      { name: '举手', value: p.handraise }, { name: '点名应答', value: p.rollcall_present },
      { name: '投票', value: p.votes_cast }] }],
  }
})
</script>

<template>
  <div class="page">
    <!-- 学生 -->
    <template v-if="role === 'student'">
      <el-card class="card-gap"><template #header>我的学习进度</template>
        <el-table :data="progress" size="small">
          <el-table-column prop="course_title" label="课程" />
          <el-table-column prop="watch_minutes" label="观看(分钟)" width="100" />
          <el-table-column label="出勤" width="110"><template #default="s">{{ s.row.attendance_present }}/{{ s.row.attendance_total }}</template></el-table-column>
          <el-table-column label="作业" width="110"><template #default="s">{{ s.row.assignments_submitted }}/{{ s.row.assignments_total }}<span v-if="s.row.assignment_avg != null"> · {{ s.row.assignment_avg }}分</span></template></el-table-column>
          <el-table-column label="考试" width="120"><template #default="s">{{ s.row.exams_taken }}/{{ s.row.exams_total }}<span v-if="s.row.exam_avg != null"> · {{ s.row.exam_avg }}分</span></template></el-table-column>
          <el-table-column label="完课率" width="180"><template #default="s"><el-progress :percentage="s.row.progress_pct" /></template></el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 讲师 -->
    <template v-if="role === 'teacher'">
      <el-card class="card-gap">
        <template #header>课程统计看板</template>
        <el-select v-model="curCourse" style="width: 260px" @change="pickCourse">
          <el-option v-for="c in courses" :key="c.id" :label="`#${c.id} ${c.title}`" :value="c.id" />
        </el-select>
        <el-button size="small" style="margin-left:12px" :disabled="!stats" @click="exportData('xlsx')">导出 Excel</el-button>
        <el-button size="small" :disabled="!stats" @click="exportData('csv')">导出 CSV</el-button>
        <template v-if="stats">
          <el-row :gutter="12" style="margin-top: 16px">
            <el-col :span="6"><el-statistic title="选课学生" :value="stats.students" /></el-col>
            <el-col :span="6"><el-statistic title="总观看(分钟)" :value="stats.total_watch_minutes" /></el-col>
            <el-col :span="6"><el-statistic title="平均完课率(%)" :value="stats.avg_progress_pct" /></el-col>
            <el-col :span="6"><el-statistic title="点名应答(人次)" :value="stats.participation.rollcall_present" /></el-col>
          </el-row>
          <el-row :gutter="16" style="margin-top: 16px">
            <el-col :span="12"><el-card><EChart :option="gradeOption" /></el-card></el-col>
            <el-col :span="12"><el-card><EChart :option="partOption" /></el-card></el-col>
          </el-row>
        </template>
      </el-card>
    </template>

    <!-- 班主任 -->
    <template v-if="role === 'head_teacher'">
      <el-card class="card-gap">
        <template #header>班级学习监督</template>
        <template v-for="c in classes" :key="c.id">
          <el-button size="small" style="margin-right:8px" @click="pickClass(c.id)">{{ c.name }}</el-button>
        </template>
        <el-table v-if="clsRows" :data="clsRows.rows" size="small" style="margin-top: 12px">
          <el-table-column prop="real_name" label="学生" width="110" />
          <el-table-column prop="course_title" label="课程" />
          <el-table-column prop="watch_minutes" label="观看(分钟)" width="110" />
          <el-table-column label="出勤率" width="110"><template #default="s">{{ s.row.attendance_rate ?? '-' }}%</template></el-table-column>
          <el-table-column label="作业提交" width="100"><template #default="s">{{ s.row.assignments_submitted }}/{{ s.row.assignments_total }}</template></el-table-column>
          <el-table-column label="考试均分" width="100"><template #default="s">{{ s.row.exam_avg ?? '-' }}</template></el-table-column>
          <el-table-column label="完课率" width="180"><template #default="s"><el-progress :percentage="s.row.progress_pct" /></template></el-table-column>
        </el-table>
        <p v-else class="muted">请选择班级</p>
      </el-card>
    </template>

    <!-- 管理员 -->
    <template v-if="role === 'admin'">
      <el-card class="card-gap" v-if="overview">
        <template #header>平台总览</template>
        <el-row :gutter="12">
          <el-col :span="4"><el-statistic title="用户数" :value="overview.users" /></el-col>
          <el-col :span="4"><el-statistic title="学生" :value="overview.students" /></el-col>
          <el-col :span="4"><el-statistic title="上线课程" :value="overview.courses_online" /></el-col>
          <el-col :span="4"><el-statistic title="完成直播" :value="overview.schedules_finished" /></el-col>
          <el-col :span="4"><el-statistic title="直播时长(分)" :value="overview.live_minutes" /></el-col>
          <el-col :span="4"><el-statistic title="观看总时长(分)" :value="overview.total_watch_minutes" /></el-col>
        </el-row>
      </el-card>
      <el-card><template #header>导出记录（留痕审计）</template>
        <el-table :data="exportLogs" size="small">
          <el-table-column prop="id" label="#" width="50" />
          <el-table-column prop="user_id" label="操作用户ID" width="110" />
          <el-table-column prop="report_type" label="报表" />
          <el-table-column label="参数"><template #default="s">{{ JSON.stringify(s.row.params) }}</template></el-table-column>
          <el-table-column prop="file_name" label="文件" />
          <el-table-column prop="created_at" label="时间" width="190" />
        </el-table>
      </el-card>
    </template>
  </div>
</template>
