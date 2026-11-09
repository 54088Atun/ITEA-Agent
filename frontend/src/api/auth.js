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
  me() {
    return http.get('/auth/me')
  },
  logout() {
    return http.post('/auth/logout')
  },
}