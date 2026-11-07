/**
 * 基于 fetch 的 SSE 客户端
 * EventSource 仅支持 GET,对话接口为 POST,故手动解析 text/event-stream
 *
 * 断线恢复约定:
 * - 网络错误与 5xx 可恢复;401/403 及其余确定性 4xx 不自动恢复;
 * - 恢复使用同一 request_id,总预算 30 秒(最多轮询 15 次),退避上限 5 秒。
 */

export const RECOVERY_BUDGET_MS = 30_000
export const MAX_RECOVERY_ATTEMPTS = 15
export const MAX_BACKOFF_MS = 5_000
export const BASE_BACKOFF_MS = 500

export class SseHttpError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.name = 'SseHttpError'
    this.status = status
    this.detail = detail
  }
}

/** 判断错误是否值得用同一 request_id 轮询恢复 */
export function isRecoverableError(err) {
  if (!err || err.name === 'AbortError') return false
  const status = err.status ?? err.response?.status
  if (status == null) return true // 网络中断/超时
  return status >= 500
}

/** 指数退避(毫秒),上限 5 秒 */
export function nextBackoffMs(attempt) {
  const value = BASE_BACKOFF_MS * (2 ** Math.max(0, Number(attempt) || 0))
  return Math.min(value, MAX_BACKOFF_MS)
}

/** 恢复截止时间 */
export function recoveryDeadline(now = Date.now()) {
  return now + RECOVERY_BUDGET_MS
}

/** 剩余恢复预算(毫秒,不会为负) */
export function remainingBudgetMs(deadline, now = Date.now()) {
  return Math.max(0, deadline - now)
}

/** 复用已有幂等键;缺失时才生成,保证重试/续答使用同一 request_id */
export function resolveRequestId(body = {}, createId) {
  if (!body.request_id) body.request_id = createId()
  return body.request_id
}

/**
 * @param {string} url    请求地址(如 /api/chat/stream)
 * @param {object} body   POST body(JSON)
 * @param {object} handlers 回调 { onEvent(evt), onDone(), onError(err) }
 * @returns {AbortController} 可调用 .abort() 取消
 */
export function ssePost(url, body, handlers = {}) {
  const controller = new AbortController()
  const token = localStorage.getItem('itea_token')

  ;(async () => {
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}))
        throw new SseHttpError(
          detail.detail || `请求失败(${resp.status})`,
          resp.status,
          detail,
        )
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE 帧以空行分隔,逐帧解析
        const frames = buffer.split('\n\n')
        buffer = frames.pop() // 最后一段可能不完整,留在 buffer

        for (const frame of frames) {
          const lines = frame.split('\n')
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const evt = JSON.parse(line.slice(6))
              handlers.onEvent?.(evt)
            } catch {
              // 非 JSON 帧,忽略
            }
          }
        }
      }
      handlers.onDone?.()
    } catch (err) {
      if (err.name === 'AbortError') return
      handlers.onError?.(err)
    }
  })()

  return controller
}
