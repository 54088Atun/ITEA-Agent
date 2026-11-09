import axios from 'axios'

// 续期专用实例:不挂业务拦截器,避免 401 递归
const refreshClient = axios.create({ baseURL: '/api', timeout: 10000 })
let refreshing = null

/**
 * 用 HttpOnly 刷新令牌换新访问令牌。
 * 并发调用共用同一个续期过程;失败时抛出,由调用方决定是否退出登录。
 */
export function refreshAccessToken() {
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
