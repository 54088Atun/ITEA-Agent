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
  invite(id, { email, studentId, name } = {}) {
    return http.post(`/classes/${id}/members`, {
      email,
      student_id: studentId,
      name,
    })
  },
  removeMember(id, studentId) {
    return http.delete(`/classes/${id}/members/${studentId}`)
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
