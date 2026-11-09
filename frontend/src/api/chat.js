import http from './http'

/** 历史对话接口:仅返回当前用户自己的会话 */
export const chatApi = {
  conversations(params = {}) {
    return http.get('/chat/conversations', { params })
  },
  history(sessionId) {
    return http.get(`/chat/history/${sessionId}`)
  },
  /** 按幂等键查询回答(SSE 断线续答/重试去重) */
  answer(requestId) {
    return http.get(`/chat/answer/${requestId}`)
  },
  /** 确认执行高危工具(令牌由对话流下发) */
  confirmTool(data) {
    return http.post('/chat/confirm-tool', data)
  },
  rename(sessionId, title) {
    return http.patch(`/chat/conversations/${sessionId}`, { title })
  },
  remove(sessionId) {
    return http.delete(`/chat/conversations/${sessionId}`)
  },
  /** 收藏 / 取消收藏 */
  setFavorite(sessionId, favorite) {
    return http.patch(`/chat/conversations/${sessionId}/favorite`, { favorite })
  },
  /** 人工调整会话信息分级(教师/管理员):full / auto / manual / confidential */
  setSecurityLevel(sessionId, securityLevel) {
    return http.patch(`/chat/conversations/${sessionId}/security-level`, {
      security_level: securityLevel,
    })
  },
  /** 生成或读取会话摘要 */
  summarize(sessionId, refresh = false) {
    return http.post(`/chat/conversations/${sessionId}/summary`, null, {
      params: { refresh },
      timeout: 120000,
    })
  },
  /** 导出 Markdown(Blob) */
  exportConversation(sessionId) {
    return http.get(`/chat/conversations/${sessionId}/export`, {
      responseType: 'blob',
      timeout: 60000,
    })
  },
}
