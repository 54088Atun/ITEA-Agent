import http from './http'

/** 班级接口:教师建班/邀请,学生凭码加入 */
export const classroomApi = {
  // ---------- 教师端 ----------
  list() {
    return http.get('/classes')
  },
  create(data) {
    // {name, course_id?, semester?, description?, invite_max_uses?, invite_days?}
    return http.post('/classes', data)
  },
  detail(id) {
    return http.get(`/classes/${id}`)
  },
  update(id, data) {
    // {name?, course_id?, semester?, description?, status?}
    return http.put(`/classes/${id}`, data)
  },
  archive(id) {
    return http.delete(`/classes/${id}`)
  },
  resetInvite(id, { days = 7, maxUses = 50 } = {}) {
    return http.post(`/classes/${id}/invite/reset`, null, {
      params: { days, max_uses: maxUses },
    })
  },
  members(id) {
    return http.get(`/classes/${id}/members`)
  },
  /** 班级角色与可配置权限清单 */
  permissions() {
    return http.get('/classes/permissions')
  },
  /** 班级维度学情与作业/考试统计 */
  report(id) {
    return http.get(`/classes/${id}/report`)
  },
  invite(id, { email, studentId, name, role = 'student', title, permissions } = {}) {
    return http.post(`/classes/${id}/members`, {
      email,
      student_id: studentId,
      name,
      role,
      title,
      permissions,
    })
  },
  /** 班主任/任课教师调整成员角色 */
  assignRole(id, userId, { role, title, permissions } = {}) {
    return http.patch(`/classes/${id}/members/${userId}/role`, {
      role, title, permissions,
    })
  },
  /** 任课教师设置自己在本班的头衔 */
  setMyTitle(id, title) {
    return http.patch(`/classes/${id}/me/title`, { title })
  },
  removeMember(id, studentId) {
    return http.delete(`/classes/${id}/members/${studentId}`)
  },
  /** 批量导入学生(CSV/XLSX) */
  importMembers(id, file) {
    const form = new FormData()
    form.append('file', file)
    return http.post(`/classes/${id}/members/import`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  },
  /** 学生转班 */
  transferMember(id, studentId, targetClassId) {
    return http.post(`/classes/${id}/members/${studentId}/transfer`, {
      target_class_id: targetClassId,
    })
  },
  /** 班级公告:成员可看,班主任/授权角色可发 */
  announcements(id) {
    return http.get(`/classes/${id}/announcements`)
  },
  createAnnouncement(id, content) {
    return http.post(`/classes/${id}/announcements`, { content })
  },

  // ---------- 学生端 ----------
  mine() {
    return http.get('/classes/student/mine')
  },
  join(inviteCode) {
    return http.post('/classes/student/join', { invite_code: inviteCode })
  },
  leave(id) {
    return http.post(`/classes/${id}/leave`)
  },
}
