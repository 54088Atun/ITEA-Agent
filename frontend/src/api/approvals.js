import http from './http'

/** 写操作审批目录与审计(AG-07) */
export const approvalsApi = {
  /** 写操作目录:[{key,label,level,level_label,target_type,roles}] */
  actions() {
    return http.get('/approvals/actions')
  },
  /** 审计记录:scope=me 仅自己;管理员可传 all */
  logs(params = {}) {
    return http.get('/approvals/logs', { params })
  },
}
