import http from './http'

export const authApi = {
  login(email, password) {
    return http.post('/auth/login', { email, password })
  },
  register(email, password, name, role) {
    return http.post('/auth/register', { email, password, name, role })
  },
  me() {
    return http.get('/auth/me')
  },
}