import http from './http'

/** 题库、AI 出题与在线考试 */
export const examApi = {
  // ---------- 题库 ----------
  questions(courseId, params = {}) {
    return http.get('/teacher/questions', { params: { course_id: courseId, ...params } })
  },
  createQuestion(data) {
    // {course_id, kp_id?, type, stem, options:[{key,text}], answer, analysis?, difficulty}
    return http.post('/teacher/questions', data)
  },
  updateQuestion(id, data) {
    return http.put(`/teacher/questions/${id}`, data)
  },
  archiveQuestion(id) {
    return http.delete(`/teacher/questions/${id}`)
  },
  // ---------- AI 出题草稿 ----------
  createQuestionDrafts(courseId, data) {
    // {count, kp_ids?, types?}
    return http.post(`/teacher/courses/${courseId}/question-drafts`, data, {
      timeout: 180000,
    })
  },
  questionDrafts(courseId) {
    return http.get(`/teacher/courses/${courseId}/question-drafts`)
  },
  adoptDraft(draftId, data) {
    // {indices?, adopt_all?}
    return http.post(`/teacher/question-drafts/${draftId}/adopt`, data)
  },
  discardDraft(draftId) {
    return http.delete(`/teacher/question-drafts/${draftId}`)
  },
  // ---------- 考试科目/考核项建议 ----------
  createExamPlanDraft(courseId, data) {
    // {duration_minutes?, total_score?}
    return http.post(`/teacher/courses/${courseId}/exam-plan-drafts`, data, {
      timeout: 180000,
    })
  },
  /** status 可选 draft / adopted / discarded */
  examPlanDrafts(courseId, status) {
    return http.get(`/teacher/courses/${courseId}/exam-plan-drafts`, {
      params: status ? { status } : {},
    })
  },
  adoptExamPlanDraft(draftId) {
    return http.post(`/teacher/exam-plan-drafts/${draftId}/adopt`)
  },
  discardExamPlanDraft(draftId) {
    return http.delete(`/teacher/exam-plan-drafts/${draftId}`)
  },
  // ---------- 试卷(教师) ----------
  exams() {
    return http.get('/teacher/exams')
  },
  createExam(data) {
    return http.post('/teacher/exams', data)
  },
  exam(id) {
    return http.get(`/teacher/exams/${id}`)
  },
  publishExam(id, confirm = false) {
    return http.post(`/teacher/exams/${id}/publish`, null, {
      params: { confirm },
    })
  },
  closeExam(id, confirm = false) {
    return http.post(`/teacher/exams/${id}/close`, null, {
      params: { confirm },
    })
  },
  examResults(id) {
    return http.get(`/teacher/exams/${id}/results`)
  },
  /** 单个答卷详情(含待批改简答) */
  examRecord(recordId) {
    return http.get(`/teacher/exam-records/${recordId}`)
  },
  /** AI 简答评分建议(不生效) */
  aiGradeRecord(recordId) {
    return http.post(`/teacher/exam-records/${recordId}/ai-grade`, null, {
      timeout: 180000,
    })
  },
  /** 教师确认简答得分 */
  confirmRecord(recordId, scores) {
    return http.post(`/teacher/exam-records/${recordId}/confirm`, { scores })
  },
  // ---------- 学生 ----------
  myExams() {
    return http.get('/student/exams')
  },
  myExam(id) {
    return http.get(`/student/exams/${id}`)
  },
  /** 开始计时并绑定当前浏览器客户端 */
  startExam(id, clientId) {
    return http.post(`/student/exams/${id}/start`, null, {
      params: { client_id: clientId },
    })
  },
  /** 答题心跳:上报客户端、切屏、复制和粘贴次数 */
  heartbeat(id, monitoring) {
    return http.post(`/student/exams/${id}/heartbeat`, monitoring)
  },
  submitExam(id, answers, monitoring) {
    // answers: {question_id: "A" | "A,B" | "true" | "简答文本"}
    return http.post(`/student/exams/${id}/submit`, { answers, ...monitoring })
  },
}
