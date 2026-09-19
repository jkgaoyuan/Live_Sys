import { reactive } from 'vue'

export const auth = reactive({
  token: localStorage.getItem('ls_token') || null,
  user: JSON.parse(localStorage.getItem('ls_user') || 'null'),
  set(login) {
    this.token = login.access_token
    this.user = login.user
    localStorage.setItem('ls_token', login.access_token)
    localStorage.setItem('ls_user', JSON.stringify(login.user))
  },
  clear() {
    this.token = null
    this.user = null
    localStorage.removeItem('ls_token')
    localStorage.removeItem('ls_user')
  },
})

export const ROLE_NAME = { admin: '管理员', teacher: '讲师', student: '学生', head_teacher: '班主任' }
