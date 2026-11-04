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
  /** 上传头像:PNG/JPG/WEBP,≤2MB */
  uploadAvatar(file) {
    const form = new FormData()
    form.append('file', file)
    return http.post('/me/avatar', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  },
  /** 退出全部设备:服务端递增令牌版本,旧登录态立即失效 */
  logoutAll() {
    return http.post('/me/logout-all')
  },
  /** 导出本人数据(JSON Blob) */
  exportData() {
    return http.get('/me/export', { responseType: 'blob', timeout: 60000 })
  },
  /** 注销账号(不可恢复) */
  deactivate(password, confirm) {
    return http.post('/me/deactivate', { password, confirm })
  },
  /** 隐私可见范围:姓名/邮箱/学习记录 */
  privacy() {
    return http.get('/me/privacy')
  },
  updatePrivacy(data) {
    return http.put('/me/privacy', data)
  },
}
