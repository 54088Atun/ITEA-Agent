import http from './http'

/** 统一课程码:教师复制课程,学生加入班级 */
export const codeApi = {
  preview(code) {
    return http.get(`/codes/${encodeURIComponent(code)}`)
  },
  redeem(code) {
    return http.post('/codes/redeem', { code })
  },
}
