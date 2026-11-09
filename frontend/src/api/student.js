import http from './http'

export const studentApi = {
  /** 学习总览:进度、薄弱点、到期复习、待交作业、待考考试一次返回 */
  learningOverview(courseId) {
    return http.get('/student/learning-overview', {
      params: { course_id: courseId || undefined },
    })
  },
  /** 下一步建议:按截止时间与薄弱程度排序,不调用模型 */
  recommendations(courseId, limit = 8) {
    return http.get('/student/recommendations', {
      params: { course_id: courseId || undefined, limit },
    })
  },
  /** 我的课程(已加入) → [{id, name, code, syllabus, semester, overall_progress}] */
  courses() {
    return http.get('/student/courses')
  },
  /** 加入课程(幂等) → {course_id, profile_id, joined} */
  enroll(courseId) {
    return http.post(`/student/courses/${courseId}/enroll`)
  },
  /** 学习进度与知识点掌握度 → {course_id, overall_progress, mastery: [{kp_id, kp_name, mastery_level}]} */
  progress(courseId) {
    return http.get(`/student/progress/${courseId}`)
  },
  /** 提交练习 → {id, profile_id, kp_id, type, content, is_correct, created_at} */
  practice(payload) {
    // {course_id, kp_id?, type: in_class|variant|code, content, is_correct?}
    return http.post('/student/practice', payload)
  },
  /** 错题列表 → [{id, kp_id, question_content, error_type, created_at}] */
  wrongQuestions(courseId, limit = 50) {
    return http.get('/student/wrong-questions', { params: { course_id: courseId, limit } })
  },
  /** 复习计划 → [{id, wrong_question_id, next_review_at, review_count, interval_days, status}] */
  reviewPlans(courseId, status = 'pending') {
    return http.get('/student/review-plans', { params: { course_id: courseId, status } })
  },
  /** 标记复习完成(遗忘曲线推进) → {id, status, next_review_at} */
  completeReviewPlan(id) {
    return http.post(`/student/review-plans/${id}/complete`)
  },
  /** 面试记录 → [{id, round, question, answer, score, feedback, created_at}] */
  interviewRecords(courseId) {
    return http.get('/student/interview/records', { params: { course_id: courseId } })
  },
  /** 切换本人面试记录的分享范围：private（仅自己）/ teacher（授权教师） */
  updateInterviewVisibility(id, visibility) {
    return http.patch(`/student/interview/records/${id}/visibility`, { visibility })
  },
  /** 持久化通知列表与未读数 */
  notifications(params = {}) {
    return http.get('/student/notifications', { params })
  },
  markNotificationRead(id) {
    return http.post(`/student/notifications/${id}/read`)
  },
  markAllNotificationsRead() {
    return http.post('/student/notifications/read-all')
  },
  notificationPreferences() {
    return http.get('/student/notification-preferences')
  },
  updateNotificationPreferences(data) {
    return http.put('/student/notification-preferences', data)
  },
  /** 按课程知识点生成练习 → {items: [{question, kp_name, hint}]} */
  generatePractice(courseId, count = 3) {
    return http.post('/student/practice/generate', { course_id: courseId, count }, {
      timeout: 120000,
    })
  },
  /** 加入错题本(自动创建首轮复习计划) */
  createWrongQuestion(data) {
    return http.post('/student/wrong-questions', data)
  },
  /** 教师发布的面试作业 */
  interviewAssignments() {
    return http.get('/student/interview-assignments')
  },
  /** 我的作业/考试 → [{id, title, kind, course_name, teacher_name, due_at, state, score}] */
  assignments() {
    return http.get('/student/assignments')
  },
  /** 作业详情(截止前不含参考答案;未确认不含 AI 建议) */
  assignment(id) {
    return http.get(`/student/assignments/${id}`)
  },
  /** 提交作业 → {id, assignment_id, state, submitted_at} */
  submitAssignment(id, data) {
    // {content, attachment_url?, draft?}
    return http.post(`/student/assignments/${id}/submit`, data)
  },
  /** 保存学生私有草稿，不进入教师待批列表 */
  saveAssignmentDraft(id, data) {
    return http.post(`/student/assignments/${id}/submit`, { ...data, draft: true })
  },
}

/** 面试开始为 SSE 流,统一用 utils/sse.js 的 ssePost 调用 /api/student/interview/start */
export const INTERVIEW_START_URL = '/api/student/interview/start'
