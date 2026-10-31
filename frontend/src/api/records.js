import http from './http'

/** 学习/发布记录与能力开关 */
export const recordsApi = {
  /** 学生学习记录时间线 */
  studentRecords(limit = 80) {
    return http.get('/student/records', { params: { limit } })
  },
  /** 教师发布记录(可按班级筛选) */
  teacherPublishRecords(classId = null, limit = 50) {
    return http.get('/teacher/publish-records', {
      params: { class_id: classId || undefined, limit },
    })
  },
  /** 灰度开关与配额 */
  features() {
    return http.get('/config/features')
  },
}
