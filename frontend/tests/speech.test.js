import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import http from '../src/api/http.js'
import {
  isSpeechActive,
  isSpeechSupported,
  markdownToPlainText,
  speakMarkdown,
  stopSpeech,
} from '../src/utils/speech.js'

function mockAudioEnvironment(post) {
  const audioInstances = []
  const calls = []
  const revoked = []
  class FakeAudio {
    constructor(src) {
      this.src = src
      audioInstances.push(this)
    }
    play() {
      this.playing = true
      calls.push('play')
      return Promise.resolve()
    }
    pause() {
      this.playing = false
      calls.push('pause')
    }
  }
  globalThis.window = {
    Audio: FakeAudio,
    URL: {
      createObjectURL() { return 'blob:ai-speech' },
      revokeObjectURL(url) { revoked.push(url) },
    },
  }
  const originalPost = http.post
  http.post = post
  return {
    audioInstances,
    calls,
    revoked,
    restore() {
      stopSpeech()
      http.post = originalPost
      delete globalThis.window
    },
  }
}

test('检测浏览器是否支持 AI 音频播放', () => {
  assert.equal(isSpeechSupported(), false)
  globalThis.window = {}
  assert.equal(isSpeechSupported(), false)
  globalThis.window = {
    Audio: class {},
    URL: { createObjectURL() {} },
  }
  assert.equal(isSpeechSupported(), true)
  delete globalThis.window
})

test('Markdown 转为保留语义的纯文本', () => {
  const markdown = '# 学习计划\n\n**重点**：访问 [课程](https://example.com) 并执行 `npm test`。'

  assert.equal(
    markdownToPlainText(markdown),
    '学习计划\n重点：访问 课程 并执行 npm test。',
  )
})

test('列表、图片、代码围栏和 HTML 不朗读原始标记', () => {
  const markdown = [
    '## 操作步骤',
    '',
    '- **安装**依赖',
    '- 查看 ![运行界面](screenshot.png)',
    '',
    '```js',
    'console.log("完成")',
    '```',
    '',
    '<p>正文&nbsp;&amp;&nbsp;结束</p>',
  ].join('\n')

  assert.equal(
    markdownToPlainText(markdown),
    '操作步骤\n安装依赖\n查看 运行界面\nconsole.log("完成")\n正文 & 结束',
  )
})

test('从 AI 语音接口获取自然音频并播放，结束后释放资源', async () => {
  const requests = []
  const env = mockAudioEnvironment(async (...args) => {
    requests.push(args)
    return new Blob(['mp3-audio'], { type: 'audio/mpeg' })
  })

  try {
    assert.equal(await speakMarkdown('# 自然回答'), true)
    assert.equal(requests.length, 1)
    assert.equal(requests[0][0], '/speech')
    assert.deepEqual(requests[0][1], { text: '自然回答' })
    assert.equal(requests[0][2].responseType, 'blob')
    assert.ok(requests[0][2].signal)
    assert.equal(env.audioInstances.length, 1)
    assert.equal(env.audioInstances[0].src, 'blob:ai-speech')
    assert.deepEqual(env.calls, ['play'])
    assert.equal(isSpeechActive(), true)

    env.audioInstances[0].onend()
    assert.equal(isSpeechActive(), false)
    assert.deepEqual(env.revoked, ['blob:ai-speech'])
  } finally {
    env.restore()
  }
})

test('切换回答会中止旧合成且旧结果不会串音', async () => {
  const requests = []
  let resolveOld
  const env = mockAudioEnvironment((url, body, config) => {
    requests.push(config)
    if (body.text === '旧回答') {
      return new Promise((resolve) => { resolveOld = resolve })
    }
    return Promise.resolve(new Blob(['new-audio']))
  })

  try {
    const oldSpeech = speakMarkdown('旧回答')
    assert.equal(await speakMarkdown('新回答'), true)
    assert.equal(requests[0].signal.aborted, true)

    resolveOld(new Blob(['old-audio']))
    assert.equal(await oldSpeech, false)
    assert.equal(env.audioInstances.length, 1)
    assert.deepEqual(env.calls, ['play'])
  } finally {
    env.restore()
  }
})

test('主动停止会暂停音频并释放活动状态', async () => {
  const env = mockAudioEnvironment(async () => new Blob(['mp3-audio']))

  try {
    await speakMarkdown('待停止的回答')
    assert.equal(isSpeechActive(), true)
    stopSpeech()
    assert.deepEqual(env.calls, ['play', 'pause'])
    assert.equal(isSpeechActive(), false)
    assert.deepEqual(env.revoked, ['blob:ai-speech'])
  } finally {
    env.restore()
  }
})

test('AI 合成异常会清理状态并回报错误', async () => {
  const env = mockAudioEnvironment(async () => {
    throw new Error('speech unavailable')
  })

  try {
    let errorCount = 0
    assert.equal(await speakMarkdown('异常回答', {
      onError: () => { errorCount += 1 },
    }), false)
    assert.equal(errorCount, 1)
    assert.equal(isSpeechActive(), false)
  } finally {
    env.restore()
  }
})

test('旧音频结束事件不影响新朗读', async () => {
  const events = []
  const env = mockAudioEnvironment(async () => new Blob(['mp3-audio']))

  try {
    await speakMarkdown('旧回答', { onEnd: () => events.push('old-end') })
    const oldEnd = env.audioInstances[0].onend
    await speakMarkdown('新回答', { onEnd: () => events.push('new-end') })

    oldEnd()
    assert.equal(isSpeechActive(), true)
    assert.deepEqual(events, [])

    env.audioInstances[1].onend()
    assert.equal(isSpeechActive(), false)
    assert.deepEqual(events, ['new-end'])
  } finally {
    env.restore()
  }
})

const chatWindowSource = readFileSync(
  new URL('../src/components/ChatWindow.vue', import.meta.url),
  'utf8',
)

test('ChatWindow 提供 AI 朗读切换和不支持提示', () => {
  assert.match(chatWindowSource, /from '\.\.\/utils\/speech\.js'/)
  assert.match(chatWindowSource, /@click="toggleSpeech\(msg, i\)"/)
  assert.match(chatWindowSource, /speakingIndex === i \? '停止朗读' : '朗读'/)
  assert.match(chatWindowSource, /async function toggleSpeech/)
  assert.match(chatWindowSource, /await speakMarkdown/)
  assert.match(chatWindowSource, /当前浏览器不支持朗读/)
})

test('ChatWindow 在切换历史、新对话和卸载时停止朗读', () => {
  assert.match(
    chatWindowSource,
    /async function openConversation\(item\) \{\s*if \(streaming\.value\) return\s*stopAnswerSpeech\(\)/,
  )
  assert.match(chatWindowSource, /function newConversation\(\) \{\s*stopAnswerSpeech\(\)/)
  assert.match(chatWindowSource, /onBeforeUnmount\(\(\) => \{\s*stopAnswerSpeech\(\)/)
})
