import http from './http'

export const teacherApi = {
  /** 课程列表(教师看自己的,admin 看全部) → 数组
   *  params: { keyword?, semester?, audit_status?, lifecycle? }
   */
  courses(params = {}) {
    return http.get('/teacher/courses', { params })
  },
  createCourse(data) {
    // {name, code, syllabus, semester}
    return http.post('/teacher/courses', data)
  },
  course(id) {
    return http.get(`/teacher/courses/${id}`)
  },
  /** 课程概览:素材、知识点、班级、作业、考试一次返回 */
  courseOverview(id) {
    return http.get(`/teacher/courses/${id}/overview`)
  },
  /** 待批改队列:按课程聚合跨作业的待批改提交,params: {assignment_id?, class_id?, page?, page_size?} */
  gradingQueue(id, params = {}) {
    return http.get(`/teacher/courses/${id}/grading-queue`, { params })
  },
  /** 复制自身课程结构(可覆盖名称/代码/学期) */
  duplicateCourse(id, data = {}) {
    return http.post(`/teacher/courses/${id}/duplicate`, data)
  },
  /** 可作为模板复制的课程列表(含知识点/资料数量) */
  courseTemplates() {
    return http.get('/teacher/course-templates')
  },
  updateCourse(id, data) {
    return http.put(`/teacher/courses/${id}`, data)
  },
  archiveCourse(id) {
    return http.post(`/teacher/courses/${id}/archive`)
  },
  deleteCourse(id) {
    return http.delete(`/teacher/courses/${id}`)
  },
  restoreCourse(id) {
    return http.post(`/teacher/courses/${id}/restore`)
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
  /** 单个学生的课程学情:进度/掌握度/薄弱点/错题/复习/面试 */
  studentCourseOverview(courseId, studentId) {
    return http.get(`/teacher/courses/${courseId}/students/${studentId}/overview`)
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
  /** 按课程发布公告:落到该课程下的班级公告板,classId 为空则发给课程下全部班级 */
  publishCourseAnnouncement(courseId, content, classId = null) {
    return http.post(`/teacher/courses/${courseId}/announcement`, {
      content,
      class_id: classId,
    })
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
  /** 学生授权给当前教师查看的面试记录，可按课程或作业过滤 */
  interviewRecords(params = {}) {
    return http.get('/teacher/interview-records', { params })
  },
  // ---------- 作业 / 考试 ----------
  /** 我发布的作业与考试 → [{id, title, kind, course_id, class_id, due_at, status, submission_count, pending_count}] */
  assignments() {
    return http.get('/teacher/assignments')
  },
  createAssignment(data) {
    // {title, kind, course_id?, class_id?, description?, reference_answer?, due_days?, allow_late?, publish?}
    return http.post('/teacher/assignments', data)
  },
  assignment(id) {
    return http.get(`/teacher/assignments/${id}`)
  },
  publishAssignment(id, confirm = false) {
    return http.post(`/teacher/assignments/${id}/publish`, null, {
      params: { confirm },
    })
  },
  /** 批量发布:dry_run=true 只预演,确认后统一发布 */
  batchPublishAssignments(assignmentIds, dryRun = true) {
    return http.post(
      '/teacher/assignments/batch-publish',
      { assignment_ids: assignmentIds, dry_run: dryRun },
      { params: { confirm: !dryRun } },
    )
  },
  /** 提醒未提交学生:dry_run=true 只预演 */
  remindAssignment(id, { dryRun = true, message = null } = {}) {
    return http.post(`/teacher/assignments/${id}/remind`, {
      dry_run: dryRun,
      message,
    })
  },
  closeAssignment(id, confirm = false) {
    return http.post(`/teacher/assignments/${id}/close`, null, {
      params: { confirm },
    })
  },
  setAssignmentAllowLate(id, enabled) {
    return http.post(`/teacher/assignments/${id}/allow-late`, null, {
      params: { enabled },
    })
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
  /** 对指定学生的作业给出成绩与反馈(等价于确认该次提交) */
  feedbackStudent(studentId, { assignmentId, score, feedback = null }) {
    return http.post(
      `/teacher/students/${studentId}/feedback`,
      { assignment_id: assignmentId, score, feedback },
      { params: { confirm: true } },
    )
  },
  // ---------- 课程分享码 ----------
  createShare(courseId, data = {}, confirm = false) {
    // {expires_days?, max_uses?}
    return http.post(`/teacher/courses/${courseId}/shares`, data, {
      params: { confirm },
    })
  },
  shares(courseId) {
    return http.get(`/teacher/courses/${courseId}/shares`)
  },
  revokeShare(shareId, confirm = false) {
    return http.delete(`/teacher/shares/${shareId}`, {
      params: { confirm },
    })
  },
  /** 凭分享码复制课程快照(不含学生数据) */
  importCourse(code) {
    return http.post('/teacher/courses/import', { code })
  },
}

/** 教案生成 SSE 地址(配合 utils/sse.js 的 ssePost 使用) */
export const LESSON_PLAN_URL = '/api/teacher/lesson-plan'
