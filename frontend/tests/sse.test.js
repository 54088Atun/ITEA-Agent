import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ssePost, SseHttpError, isRecoverableError, nextBackoffMs,
  recoveryDeadline, remainingBudgetMs, resolveRequestId,
  RECOVERY_BUDGET_MS, MAX_RECOVERY_ATTEMPTS, MAX_BACKOFF_MS, BASE_BACKOFF_MS,
} from '../src/utils/sse.js'

function withGlobals(t, { fetchImpl, token = 'token' }) {
  const originalFetch = globalThis.fetch
  const originalStorage = globalThis.localStorage
  globalThis.fetch = fetchImpl
  globalThis.localStorage = { getItem: () => token }
  t.after(() => {
    globalThis.fetch = originalFetch
    globalThis.localStorage = originalStorage
  })
}

test('SSE 非 2xx 错误保留 HTTP status', async (t) => {
  withGlobals(t, {
    fetchImpl: async () => ({
      ok: false,
      status: 403,
      json: async () => ({ detail: '无权限' }),
    }),
  })

  const err = await new Promise((resolve) => {
    ssePost('/api/chat/stream', { q: 1 }, { onError: resolve })
  })

  assert.ok(err instanceof SseHttpError)
  assert.equal(err.status, 403)
  assert.equal(err.message, '无权限')
})

test('SSE 解析事件并保留请求幂等键', async (t) => {
  let sentBody
  withGlobals(t, {
    fetchImpl: async (url, options) => {
      sentBody = JSON.parse(options.body)
      return new Response(
        'data: {"type":"token","data":{"content":"hi"}}\n\n'
        + 'data: {"type":"done","data":{}}\n\n',
        { status: 200 },
      )
    },
  })

  const events = []
  await new Promise((resolve) => {
    ssePost('/x', { request_id: 'req-1' }, {
      onEvent: (evt) => events.push(evt),
      onDone: resolve,
    })
  })

  assert.equal(sentBody.request_id, 'req-1')
  assert.deepEqual(events.map((evt) => evt.type), ['token', 'done'])
})

test('取消 SSE 不触发 onError', async (t) => {
  withGlobals(t, {
    fetchImpl: (url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        const err = new Error('aborted')
        err.name = 'AbortError'
        reject(err)
      })
    }),
  })

  let called = false
  const controller = ssePost('/x', {}, { onError: () => { called = true } })
  controller.abort()
  await new Promise((resolve) => setTimeout(resolve, 10))

  assert.equal(called, false)
})

test('错误分类:网络与 5xx 可恢复,401/403/4xx 不可恢复', () => {
  assert.equal(isRecoverableError(new Error('network')), true)
  assert.equal(isRecoverableError(Object.assign(new Error('x'), { status: 500 })), true)
  assert.equal(isRecoverableError(Object.assign(new Error('x'), { status: 503 })), true)
  assert.equal(isRecoverableError(Object.assign(new Error('x'), { status: 401 })), false)
  assert.equal(isRecoverableError(Object.assign(new Error('x'), { status: 403 })), false)
  assert.equal(isRecoverableError(Object.assign(new Error('x'), { status: 404 })), false)
  assert.equal(isRecoverableError(Object.assign(new Error('x'), { status: 422 })), false)

  const aborted = new Error('aborted')
  aborted.name = 'AbortError'
  assert.equal(isRecoverableError(aborted), false)
})

test('退避上限 5 秒,总预算 30 秒且最多轮询 15 次', () => {
  assert.equal(MAX_RECOVERY_ATTEMPTS, 15)
  assert.equal(nextBackoffMs(0), BASE_BACKOFF_MS)
  assert.equal(nextBackoffMs(1), 1000)
  assert.equal(nextBackoffMs(2), 2000)
  assert.equal(nextBackoffMs(3), 4000)
  assert.equal(nextBackoffMs(4), MAX_BACKOFF_MS)
  assert.equal(nextBackoffMs(20), MAX_BACKOFF_MS)

  const now = 1_000_000
  const deadline = recoveryDeadline(now)
  assert.equal(deadline, now + RECOVERY_BUDGET_MS)
  assert.equal(remainingBudgetMs(deadline, now + 1000), RECOVERY_BUDGET_MS - 1000)
  assert.equal(remainingBudgetMs(deadline, deadline + 1), 0)
})

test('重试复用同一 request_id', () => {
  let generated = 0
  const createId = () => {
    generated += 1
    return `new-${generated}`
  }

  const body = {}
  assert.equal(resolveRequestId(body, createId), 'new-1')
  assert.equal(resolveRequestId(body, createId), 'new-1')
  assert.equal(generated, 1)

  assert.equal(resolveRequestId({ request_id: 'keep' }, createId), 'keep')
  assert.equal(generated, 1)
})
