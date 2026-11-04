import http from './http'

/** 用户可控能力:执行时间线、暂停运行、记忆管理、回答反馈 */
export const agentApi = {
  /** 本人一次运行的 step 时间线 */
  timeline(runId) {
    return http.get(`/agent/runs/${runId}/timeline`)
  },
  /** 暂停/取消正在生成的运行 */
  cancelRun(runId) {
    return http.post(`/agent/runs/${runId}/cancel`)
  },
  /** 运行计划与历史调整 */
  plan(runId) {
    return http.get(`/agent/runs/${runId}/plan`)
  },
  /** 运行中途调整计划:下一超级步生效 */
  revisePlan(runId, instruction) {
    return http.post(`/agent/runs/${runId}/plan`, { instruction })
  },
  /** 我的长期记忆 */
  memories(params = {}) {
    return http.get('/agent/memory', { params })
  },
  deleteMemory(id) {
    return http.delete(`/agent/memory/${id}`)
  },
  /** 对一条回答点赞/点踩 */
  feedback(payload) {
    return http.post('/agent/feedback', payload)
  },
}
