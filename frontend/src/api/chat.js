import http from './http'

/** 历史对话接口:仅返回当前用户自己的会话 */
export const chatApi = {
  conversations() {
    return http.get('/chat/conversations')
  },
  history(sessionId) {
    return http.get(`/chat/history/${sessionId}`)
  },
  rename(sessionId, title) {
    return http.patch(`/chat/conversations/${sessionId}`, { title })
  },
  remove(sessionId) {
    return http.delete(`/chat/conversations/${sessionId}`)
  },
}
