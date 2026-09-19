<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'

const route = useRoute()
const sid = Number(route.params.sid)
const rec = ref(null)
const pos = ref(0)
const total = ref(0)
const isTeacher = computed(() => auth.user.role === 'teacher')
const isStaff = computed(() => ['teacher', 'admin'].includes(auth.user.role))

async function load() {
  try {
    rec.value = await http.get(`/schedules/${sid}/recording`)
    pos.value = rec.value.last_position || 0
    total.value = rec.value.my_seconds || 0
  } catch (e) { ElMessage.error(err(e)) }
}
onMounted(load)

async function transcode() {
  await http.post(`/recordings/${rec.value.id}/transcode`, { duration: 3600 })
  ElMessage.success('转码完成（模拟 FFmpeg 任务回调）')
  load()
}

async function watch(secs) {
  try {
    const d = await http.put(`/recordings/${rec.value.id}/heartbeat`, { seconds: secs, position: Math.min(pos.value + secs, rec.value.duration) })
    total.value = d.total_seconds
    pos.value = d.last_position
  } catch (e) { ElMessage.error(err(e)) }
}
</script>

<template>
  <div class="page" v-if="rec">
    <el-card>
      <template #header>录播回放 · 排课 #{{ sid }}（录制 #{{ rec.id }}）</template>
      <el-tag v-if="rec.status === 'transcoding'" type="warning">转码中，暂不可播放</el-tag>
      <el-button v-if="rec.status === 'transcoding' && isStaff" size="small" type="primary" @click="transcode">模拟转码完成回调</el-button>
      <template v-if="rec.status === 'ready'">
        <div class="video-stage">
          <div style="font-size:44px">▶️</div>
          <div>HLS：{{ rec.hls_url }}（播放器接入占位）</div>
        </div>
        <div style="margin:16px 0">
          播放位置
          <el-slider v-model="pos" :max="rec.duration" :format-tooltip="(v) => `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`" style="display:inline-block;width:400px;vertical-align:middle;margin:0 12px" />
          <span class="muted">时长 {{ Math.floor(rec.duration / 60) }} 分钟</span>
        </div>
        <div style="display:flex;gap:10px;align-items:center">
          <el-button type="primary" @click="watch(30)">模拟观看 30 秒</el-button>
          <el-button @click="watch(60)">模拟观看 60 秒</el-button>
          <span>服务端累计有效观看：<b>{{ total }}</b> 秒；刷新页面将从 <b>{{ pos }}</b> 秒断点续播</span>
        </div>
        <p class="muted" style="margin-top:10px">观看行为写入 watch_logs（学生×目标×自然日），驱动进度/统计/导出全链路</p>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.video-stage { height: 240px; background: #101418; color: #dfe4ea; border-radius: 8px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; margin-top: 10px; }
</style>
