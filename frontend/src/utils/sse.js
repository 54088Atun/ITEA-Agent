/**
 * 基于 fetch 的 SSE 客户端
 * EventSource 仅支持 GET,对话接口为 POST,故手动解析 text/event-stream
 *
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
        throw new Error(detail.detail || `请求失败(${resp.status})`)
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