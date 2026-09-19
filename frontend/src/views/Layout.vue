<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { auth, ROLE_NAME } from '../store'

const router = useRouter()
const menus = [
  { path: '/dashboard', title: '工作台', roles: ['admin', 'teacher', 'student', 'head_teacher'] },
  { path: '/courses', title: '课程管理', roles: ['admin', 'teacher', 'student', 'head_teacher'] },
  { path: '/schedule', title: '课表 / 排课', roles: ['admin', 'teacher', 'student', 'head_teacher'] },
  { path: '/assignments', title: '作业', roles: ['teacher', 'student'] },
  { path: '/exams', title: '考试', roles: ['teacher', 'student'] },
  { path: '/users', title: '用户与班级', roles: ['admin'] },
  { path: '/demo', title: '全链路演示', roles: ['admin'] },
]
const visible = computed(() => menus.filter((m) => m.roles.includes(auth.user && auth.user.role)))

function logout() {
  auth.clear()
  router.push('/login')
}
</script>

<template>
  <el-container style="min-height: 100vh">
    <el-aside width="200px" style="background: #001529">
      <div style="color: #fff; font-size: 16px; padding: 18px 16px; font-weight: 600">Live_Sys 在线课堂</div>
      <el-menu :default-active="$route.path" router background-color="#001529" text-color="#a6b1c2" active-text-color="#409eff">
        <el-menu-item v-for="m in visible" :key="m.path" :index="m.path">{{ m.title }}</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header style="background: #fff; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 4px rgba(0,21,41,.08)">
        <div>
          <el-tag disable-transitions>{{ ROLE_NAME[auth.user && auth.user.role] }}</el-tag>
          <span style="margin-left: 10px; font-weight: 600">{{ auth.user && auth.user.real_name }}</span>
          <span class="muted" style="margin-left: 8px">@{{ auth.user && auth.user.username }}</span>
        </div>
        <el-button size="small" @click="logout">退出登录</el-button>
      </el-header>
      <el-main><router-view /></el-main>
    </el-container>
  </el-container>
</template>
