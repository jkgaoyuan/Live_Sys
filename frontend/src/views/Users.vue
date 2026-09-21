<script setup>
import { ref, onMounted } from 'vue'
import { http, err } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ROLE_NAME } from '../store'

const users = ref([]); const classes = ref([])
const uForm = ref({ username: '', password: 'Test@123', real_name: '', role: 'student', class_id: null })
const cForm = ref({ name: '' })

async function load() {
  users.value = await http.get('/users')
  classes.value = await http.get('/classes')
}
onMounted(load)

async function addUser() {
  try {
    await http.post('/users', uForm.value)
    ElMessage.success('账号已创建'); load()
  } catch (e) { ElMessage.error(err(e)) }
}
async function addClass() {
  const name = cForm.value.name.trim()
  if (!name) return ElMessage.warning('请填写班级名称')
  if (name.length > 10) return ElMessage.warning('班级名称不能超过 10 个中文字符')
  try { await http.post('/classes', { ...cForm.value, name }); ElMessage.success('班级已创建'); cForm.value.name = ''; load() }
  catch (e) { ElMessage.error(err(e)) }
}
async function delClass(c) {
  try {
    await ElMessageBox.confirm(`确定删除班级「${c.name}」？`, '删除班级', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch { return }
  try { await http.delete(`/classes/${c.id}`); ElMessage.success('班级已删除'); load() }
  catch (e) { ElMessage.error(err(e)) }
}
async function toggleUser(u) {
  const disabling = u.status === 'active'
  const word = disabling ? '删除（禁用）' : '启用'
  try {
    await ElMessageBox.confirm(`确定${word}账号「${u.real_name} @${u.username}」？${disabling ? '该用户将无法登录。' : ''}`, `${word}用户`, { type: 'warning', confirmButtonText: word, cancelButtonText: '取消' })
  } catch { return }
  try {
    await http.patch(`/users/${u.id}/status`, { status: disabling ? 'disabled' : 'active' })
    ElMessage.success(disabling ? '用户已删除（禁用）' : '用户已启用'); load()
  } catch (e) { ElMessage.error(err(e)) }
}
</script>

<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="16">
        <el-card>
          <template #header>用户列表</template>
          <el-table :data="users" size="small">
            <el-table-column prop="id" label="#" width="46" />
            <el-table-column prop="username" label="账号" width="130" />
            <el-table-column prop="real_name" label="姓名" width="110" />
            <el-table-column label="角色" width="100"><template #default="s"><el-tag size="small">{{ ROLE_NAME[s.row.role] }}</el-tag></template></el-table-column>
            <el-table-column prop="class_id" label="班级ID" width="80" />
            <el-table-column label="状态" width="80"><template #default="s"><el-tag size="small" :type="s.row.status === 'active' ? 'success' : 'info'">{{ s.row.status === 'active' ? '正常' : '已禁用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="s">
                <el-button v-if="s.row.role !== 'admin'" size="small" :type="s.row.status === 'active' ? 'danger' : 'success'" text @click="toggleUser(s.row)">
                  {{ s.row.status === 'active' ? '删除' : '启用' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="card-gap">
          <template #header>创建账号</template>
          <el-form label-width="60px">
            <el-form-item label="账号"><el-input v-model="uForm.username" /></el-form-item>
            <el-form-item label="密码"><el-input v-model="uForm.password" /></el-form-item>
            <el-form-item label="姓名"><el-input v-model="uForm.real_name" /></el-form-item>
            <el-form-item label="角色"><el-select v-model="uForm.role" style="width:100%">
              <el-option v-for="(n, k) in ROLE_NAME" :key="k" :label="n" :value="k" /></el-select></el-form-item>
            <el-form-item label="班级"><el-select v-model="uForm.class_id" clearable style="width:100%">
              <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" /></el-select></el-form-item>
          </el-form>
          <el-button type="primary" size="small" @click="addUser">创建</el-button>
        </el-card>
        <el-card>
          <template #header>班级</template>
          <div style="display:flex;gap:8px;margin-bottom:10px">
            <el-input v-model="cForm.name" size="small" placeholder="班级名" maxlength="10" show-word-limit />
            <el-button size="small" type="primary" @click="addClass">新建</el-button>
          </div>
          <el-table :data="classes" size="small">
            <el-table-column prop="id" label="#" width="46" />
            <el-table-column prop="name" label="班级" />
            <el-table-column prop="head_teacher_id" label="班主任ID" width="90" />
            <el-table-column label="操作" width="70">
              <template #default="s"><el-button size="small" type="danger" text @click="delClass(s.row)">删除</el-button></template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
