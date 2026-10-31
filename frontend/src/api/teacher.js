import http from './http'

export const teacherApi = {
  /** 课程列表(教师看自己的,admin 看全部) → 数组 */
  courses() {
    return http.get('/teacher/courses')
  },
  createCourse(data) {
    // {name, code, syllabus, semester}
    return http.post('/teacher/courses', data)
  },
  course(id) {
    return http.get(`/teacher/courses/${id}`)
  },
  updateCourse(id, data) {
    return http.put(`/teacher/courses/${id}`, data)
  },
  /** 上传素材(FormData: course_id/type/title/file) */
  uploadMaterial(courseId, type, title, file) {
    const form = new FormData()
    form.append('course_id', courseId)
    form.append('type', type)
    form.append('title', title)
    form.append('file', file)
    return http.post('/teacher/materials', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  /** 班级学情 → {course_id, course_name, student_count, avg_progress(0-100), weak_points, students} */
  classReport(courseId) {
    return http.get(`/teacher/class-report/${courseId}`)
  },
  /** 导出 → type ∈ lesson_plan / preview_sheet / report */
  exportDoc(type, courseId, data = {}) {
    return http.post('/teacher/export', { type, course_id: courseId, data })
  },
  /** 学情统计 → weakness / progress / distribution */
  stats(metric, params) {
    return http.get(`/teacher/stats/${metric}`, { params })
  },
  /** 上传课程目录/大纲,由 Agent 生成知识点与大纲草稿(不直接入库) */
  createKpDraft(courseId, file) {
    const form = new FormData()
    form.append('file', file)
    return http.post(`/teacher/courses/${courseId}/kp-drafts`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 180000,
    })
  },
  kpDrafts(courseId) {
    return http.get(`/teacher/courses/${courseId}/kp-drafts`)
  },
  /** {paths, adopt_all, apply_syllabus} */
  adoptKpDraft(draftId, payload) {
    return http.post(`/teacher/kp-drafts/${draftId}/adopt`, payload)
  },
  discardKpDraft(draftId) {
    return http.delete(`/teacher/kp-drafts/${draftId}`)
  },
  /** 面试作业:发布后学生端可见 */
  interviewAssignments() {
    return http.get('/teacher/interview-assignments')
  },
  createInterviewAssignment(data) {
    return http.post('/teacher/interview-assignments', data)
  },
  closeInterviewAssignment(id) {
    return http.delete(`/teacher/interview-assignments/${id}`)
  },
  // ---------- 作业 / 考试 ----------
  /** 我发布的作业与考试 → [{id, title, kind, course_id, class_id, due_at, status, submission_count, pending_count}] */
  assignments() {
    return http.get('/teacher/assignments')
  },
  createAssignment(data) {
    // {title, kind, course_id?, class_id?, description?, reference_answer?, due_days?, publish?}
    return http.post('/teacher/assignments', data)
  },
  assignment(id) {
    return http.get(`/teacher/assignments/${id}`)
  },
  publishAssignment(id) {
    return http.post(`/teacher/assignments/${id}/publish`)
  },
  closeAssignment(id) {
    return http.post(`/teacher/assignments/${id}/close`)
  },
  /** AI 建议批改:只写 ai_* 字段,不生效 */
  aiGradeSubmission(submissionId) {
    return http.post(`/teacher/submissions/${submissionId}/ai-grade`, null, {
      timeout: 120000,
    })
  },
  /** 教师确认正式分数 → {score, feedback, confirmed} */
  confirmSubmission(submissionId, data) {
    return http.post(`/teacher/submissions/${submissionId}/confirm`, data)
  },
  // ---------- 课程分享码 ----------
  createShare(courseId, data = {}) {
    // {expires_days?, max_uses?}
    return http.post(`/teacher/courses/${courseId}/shares`, data)
  },
  shares(courseId) {
    return http.get(`/teacher/courses/${courseId}/shares`)
  },
  revokeShare(shareId) {
    return http.delete(`/teacher/shares/${shareId}`)
  },
  /** 凭分享码复制课程快照(不含学生数据) */
  importCourse(code) {
    return http.post('/teacher/courses/import', { code })
  },
}

/** 教案生成 SSE 地址(配合 utils/sse.js 的 ssePost 使用) */
export const LESSON_PLAN_URL = '/api/teacher/lesson-plan'
