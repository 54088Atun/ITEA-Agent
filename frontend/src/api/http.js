import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截:注入 JWT
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('itea_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截:统一错误处理
http.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    // 后端无响应时 axios 只给 "timeout of 30000ms exceeded",对用户没有意义
    const timeoutMsg = err.code === 'ECONNABORTED' || /timeout/i.test(err.message || '')
      ? '服务响应超时，请检查后端是否正常运行'
      : null
    const msg = err.response?.data?.detail || timeoutMsg || err.message || '请求失败'
    if (err.response?.status === 401) {
      // token 失效,清除并跳转登录
      localStorage.removeItem('itea_token')
      localStorage.removeItem('itea_user')
      if (location.pathname !== '/login') {
        location.href = '/login'
      }
    } else {
      ElMessage.error(msg)
    }
    return Promise.reject(err)
  }
)

export default http