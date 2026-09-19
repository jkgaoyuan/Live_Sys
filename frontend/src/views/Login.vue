<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { http, err } from '../api'
import { auth } from '../store'
import { ElMessage } from 'element-plus'

const router = useRouter()
const form = ref({ username: '', password: '' })
const loading = ref(false)

const quick = [
  { label: '管理员', u: 'admin', p: 'admin123' },
  { label: '王讲师', u: 'teacher_wang', p: 'Test@123' },
  { label: '学生1', u: 'stu1', p: 'Test@123' },
  { label: '学生2', u: 'stu2', p: 'Test@123' },
  { label: '学生3', u: 'stu3', p: 'Test@123' },
  { label: '赵班主任', u: 'head1', p: 'Test@123' },
]

async function submit() {
  loading.value = true
  try {
    const d = await http.post('/auth/login', form.value)
    auth.set(d)
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(err(e))
  } finally {
    loading.value = false
  }
}

function fill(q) {
  form.value = { username: q.u, password: q.p }
  submit()
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 style="text-align: center; margin: 0 0 4px">在线课堂直播平台</h2>
      <p class="muted" style="text-align: center; margin-bottom: 20px">Vue3 + FastAPI + PostgreSQL · 全链路演示</p>
      <el-form label-width="60px">
        <el-form-item label="账号"><el-input v-model="form.username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password @keyup.enter="submit" /></el-form-item>
      </el-form>
      <el-button type="primary" style="width: 100%" :loading="loading" @click="submit">登 录</el-button>
      <el-divider>快速体验（演示数据）</el-divider>
      <div style="display: flex; flex-wrap: wrap; gap: 8px; justify-content: center">
        <el-button v-for="q in quick" :key="q.u" size="small" @click="fill(q)">{{ q.label }}</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap { min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1f6feb 0%, #7c3aed 100%); }
.login-card { width: 420px; padding: 8px 12px; }
</style>
