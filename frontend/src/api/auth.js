import http from './http'

export const authApi = {
  login(email, password, captcha = {}) {
    return http.post('/auth/login', { email, password, ...captcha })
  },
  register(payload) {
    return http.post('/auth/register', payload)
  },
  captcha() {
    return http.get('/auth/captcha')
  },
  // 发码/激活/重置由登录页内联提示,使用 silent 避免全局弹窗
  sendEmailCode(payload) {
    return http.post('/auth/email/code', payload, { silent: true })
  },
  verifyEmail(payload) {
    return http.post('/auth/email/verify', payload, { silent: true })
  },
  resetPassword(payload) {
    return http.post('/auth/password/reset', payload, { silent: true })
  },
  me() {
    return http.get('/auth/me')
  },
  logout() {
    return http.post('/auth/logout')
  },
}