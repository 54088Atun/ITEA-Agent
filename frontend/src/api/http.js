import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 续期专用实例:不走下面的拦截器,避免 401 递归
const refreshClient = axios.create({ baseURL: '/api', timeout: 10000 })
let refreshing = null

/** 用 HttpOnly 刷新令牌换新访问令牌;并发请求共用同一个续期过程 */
function refreshToken() {
  if (!refreshing) {
    refreshing = refreshClient
      .post('/auth/refresh')
      .then((resp) => {
        const token = resp.data?.access_token
        if (token) {
          localStorage.setItem('itea_token', token)
          if (resp.data?.user) {
            localStorage.setItem('itea_user', JSON.stringify(resp.data.user))
          }
        }
        return token || ''
      })
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

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
  async (err) => {
    const config = err.config || {}
    const url = config.url || ''
    // 登录接口的失败由登录页内联提示,这里不再弹全局消息,也不要清掉已有会话
    const isLoginRequest = url.includes('/auth/login')
    const isRefreshRequest = url.includes('/auth/refresh')

    // 访问令牌过期:先用刷新令牌续期,再原样重试一次
    if (
      err.response?.status === 401
      && !isLoginRequest
      && !isRefreshRequest
      && !config._retried
    ) {
      try {
        const token = await refreshToken()
        if (token) {
          config._retried = true
          config.headers = config.headers || {}
          config.headers.Authorization = `Bearer ${token}`
          return http(config)
        }
      } catch { /* 续期失败,按原有 401 流程退出登录 */ }
    }

    // 后端无响应时 axios 只给 "timeout of 30000ms exceeded",对用户没有意义
    const timeoutMsg = err.code === 'ECONNABORTED' || /timeout/i.test(err.message || '')
      ? '服务响应超时，请检查后端是否正常运行'
      : null
    const msg = err.response?.data?.detail || timeoutMsg || err.message || '请求失败'
    if (isLoginRequest) {
      return Promise.reject(err)
    }
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