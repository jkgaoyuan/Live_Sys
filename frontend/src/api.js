import axios from 'axios'
import { auth } from './store'

export const http = axios.create({ baseURL: 'http://127.0.0.1:8000/api/v1', timeout: 15000 })

http.interceptors.request.use((c) => {
  if (auth.token) c.headers.Authorization = `Bearer ${auth.token}`
  return c
})

http.interceptors.response.use(
  (r) => {
    if (r.config.responseType === 'blob') return r
    return r.data && 'data' in r.data ? r.data.data : r.data
  },
  (e) => {
    if (e.response && e.response.status === 401 && !location.pathname.startsWith('/login')) {
      auth.clear()
      location.href = '/login'
    }
    return Promise.reject(e)
  }
)

export const err = (e) => (e.response && e.response.data && e.response.data.message) || String(e)

export async function download(path, params, filename) {
  const r = await http.get(path, { params, responseType: 'blob' })
  const url = URL.createObjectURL(r.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
