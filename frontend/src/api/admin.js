import http from './http'

/** 管理端接口(全部需 admin token) */
export const adminApi = {
  // ---------- 用户管理 ----------
  users(params) {
    // {page, size, role, keyword, status}
    return http.get('/admin/users', { params })
  },
  createUser(data) {
    // {role, name, email, password}
    return http.post('/admin/users', data)
  },
  user(id) {
    return http.get(`/admin/users/${id}`)
  },
  updateUser(id, data) {
    // {role?, name?, email?}
    return http.put(`/admin/users/${id}`, data)
  },
  setUserStatus(id, status) {
    // active / disabled
    return http.patch(`/admin/users/${id}/status`, { status })
  },
  resetPassword(id, newPassword) {
    return http.patch(`/admin/users/${id}/reset-password`, { new_password: newPassword })
  },
  setAdminLevel(id, adminLevel) {
    // super / normal / observer，仅超管可调用
    return http.patch(`/admin/users/${id}/admin-level`, { admin_level: adminLevel })
  },

  // ---------- 课程审核 ----------
  courses(params) {
    // {page, size, audit_status, keyword}
    return http.get('/admin/courses', { params })
  },
  auditCourse(id, auditStatus) {
    // pending / approved / rejected
    return http.patch(`/admin/courses/${id}/audit`, { audit_status: auditStatus })
  },

  // ---------- 素材管理 ----------
  materials(params) {
    // {page, size, course_id}
    return http.get('/admin/materials', { params })
  },
  deleteMaterial(id) {
    return http.delete(`/admin/materials/${id}`)
  },

  // ---------- 风控 ----------
  riskLogs(params) {
    // {page, size, risk_type, user_id}
    return http.get('/admin/risk-logs', { params })
  },
  riskStats() {
    return http.get('/admin/risk-logs/stats')
  },

  // ---------- 日志 ----------
  interactionLogs(params) {
    // {page, size, user_id, branch, session_id}
    return http.get('/admin/interaction-logs', { params })
  },
  operationLogs(params) {
    // {page, size, admin_id, action, target_type}
    return http.get('/admin/operation-logs', { params })
  },

  // ---------- 系统配置 ----------
  config() {
    return http.get('/admin/config')
  },
  saveConfig(items) {
    // items: [{config_key, config_value}]
    return http.put('/admin/config', { items })
  },

  // ---------- 统计 ----------
  statsOverview() {
    return http.get('/admin/stats/overview')
  },
  statsUsers() {
    return http.get('/admin/stats/users')
  },
  statsCourses() {
    return http.get('/admin/stats/courses')
  },
  statsAgent() {
    return http.get('/admin/stats/agent')
  },
}
