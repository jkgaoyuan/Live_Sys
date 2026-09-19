import { createRouter, createWebHistory } from 'vue-router'
import { auth } from './store'

const routes = [
  { path: '/login', component: () => import('./views/Login.vue') },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('./views/Dashboard.vue') },
      { path: 'courses', component: () => import('./views/Courses.vue') },
      { path: 'schedule', component: () => import('./views/Schedule.vue') },
      { path: 'room/:sid', component: () => import('./views/Room.vue') },
      { path: 'replay/:sid', component: () => import('./views/Replay.vue') },
      { path: 'assignments', component: () => import('./views/Assignments.vue') },
      { path: 'exams', component: () => import('./views/Exams.vue') },
      { path: 'users', component: () => import('./views/Users.vue'), meta: { roles: ['admin'] } },
      { path: 'demo', component: () => import('./views/ChainDemo.vue'), meta: { roles: ['admin'] } },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  if (to.path === '/login') return true
  if (!auth.token) return '/login'
  const roles = to.meta && to.meta.roles
  if (roles && (!auth.user || !roles.includes(auth.user.role))) return '/dashboard'
  return true
})

export default router
