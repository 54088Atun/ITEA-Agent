import http from './http'

export const meApi = {
  profile() {
    return http.get('/me')
  },
  update(data) {
    // {name?, email?}
    return http.patch('/me', data)
  },
  changePassword(oldPassword, newPassword) {
    return http.patch('/me/password', {
      old_password: oldPassword,
      new_password: newPassword,
    })
  },
  /** 导出本人数据(JSON Blob) */
  exportData() {
    return http.get('/me/export', { responseType: 'blob', timeout: 60000 })
  },
  /** 注销账号(不可恢复) */
  deactivate(password, confirm) {
    return http.post('/me/deactivate', { password, confirm })
  },
}
