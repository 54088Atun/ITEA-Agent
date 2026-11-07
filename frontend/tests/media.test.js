import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { microphoneErrorMessage } from '../src/utils/media.js'

test('麦克风权限被拒绝时提示网站设置中的开启方法', () => {
  assert.equal(
    microphoneErrorMessage({ name: 'NotAllowedError' }),
    '麦克风权限被拒绝，请在浏览器地址栏的网站设置中允许麦克风后重试',
  )
})

test('没有麦克风设备时给出明确提示', () => {
  assert.equal(
    microphoneErrorMessage({ name: 'NotFoundError' }),
    '未检测到可用麦克风，请连接设备后重试',
  )
})

test('麦克风被占用或不可用时提示排查占用', () => {
  assert.equal(
    microphoneErrorMessage({ name: 'NotReadableError' }),
    '麦克风被其他应用占用或暂时不可用，请关闭占用应用后重试',
  )
})

test('未知录音错误使用通用权限与设备提示', () => {
  assert.equal(
    microphoneErrorMessage(new Error('unknown')),
    '无法访问麦克风，请检查浏览器权限和设备状态后重试',
  )
  assert.equal(
    microphoneErrorMessage(),
    '无法访问麦克风，请检查浏览器权限和设备状态后重试',
  )
})

const chatWindowSource = readFileSync(
  new URL('../src/components/ChatWindow.vue', import.meta.url),
  'utf8',
)

test('ChatWindow 使用独立拍照输入并复用既有图片上传链路', () => {
  const cameraInput = chatWindowSource.match(
    /<input\s+ref="cameraInput"[\s\S]*?\/>/,
  )?.[0]
  assert.ok(cameraInput, '应提供独立拍照输入')
  assert.match(cameraInput, /type="file"/)
  assert.match(cameraInput, /accept="image\/png,image\/jpeg,image\/webp"/)
  assert.match(cameraInput, /capture="environment"/)
  assert.match(cameraInput, /@change="onImageChange"/)
  assert.doesNotMatch(cameraInput, /\smultiple\b/)

  const galleryInput = chatWindowSource.match(
    /<input\s+ref="imageInput"[\s\S]*?\/>/,
  )?.[0]
  assert.ok(galleryInput, '应保留图库输入')
  assert.match(galleryInput, /\smultiple\b/)
  assert.match(chatWindowSource, /@click="pickCameraImage"/)
  assert.match(
    chatWindowSource,
    /async function onImageChange\(event\) \{[\s\S]*?await addImageFiles\(files\)/,
  )
})

test('ChatWindow 仅在点击录音后申请设备并分类反馈麦克风错误', () => {
  assert.match(chatWindowSource, /@click="toggleRecording"/)
  assert.match(
    chatWindowSource,
    /async function toggleRecording\(\) \{[\s\S]*?navigator\.mediaDevices\.getUserMedia\(\{ audio: true \}\)/,
  )
  assert.match(
    chatWindowSource,
    /import \{ microphoneErrorMessage \} from '\.\.\/utils\/media\.js'/,
  )
  assert.match(
    chatWindowSource,
    /catch \(error\) \{\s*ElMessage\.warning\(microphoneErrorMessage\(error\)\)\s*\}/,
  )
})

test('ChatWindow 在 600px 窄屏保持操作可点且无需 hover', () => {
  const narrowScreenRule = chatWindowSource.match(
    /@media \(max-width: 600px\) \{([\s\S]*?)\n\}\n<\/style>/,
  )?.[1]
  assert.ok(narrowScreenRule, '应提供 600px 窄屏规则')
  assert.match(
    narrowScreenRule,
    /\.chat__composer-foot\s*\{[^}]*flex-wrap:\s*wrap;/,
  )
  assert.match(
    narrowScreenRule,
    /\.chat__composer-actions\s*\{[^}]*flex-wrap:\s*wrap;/,
  )
  assert.match(narrowScreenRule, /\.chat__hint\s*\{[^}]*display:\s*none;/)
  assert.match(
    narrowScreenRule,
    /\.chat__composer-actions :deep\(\.el-button\)\s*\{[^}]*min-width:\s*44px;[^}]*min-height:\s*44px;/,
  )
  assert.match(narrowScreenRule, /\.msg__actions\s*\{[^}]*opacity:\s*1;/)
  assert.match(narrowScreenRule, /\.msg__action\s*\{[^}]*min-height:\s*44px;/)

  const drawerStart = chatWindowSource.indexOf('@media (max-width: 900px) {')
  const drawerEnd = chatWindowSource.indexOf('@media (max-width: 600px)', drawerStart)
  const drawerRule = chatWindowSource.slice(drawerStart, drawerEnd)

  assert.ok(drawerRule, '应提供 900px 抽屉规则')
  assert.match(drawerRule, /\.chat-side \{[\s\S]*?position: fixed;/)
  assert.match(drawerRule, /\.chat-side\.is-open \{\s*transform: translateX\(0\);/)
  assert.match(drawerRule, /\.chat__mobile-bar \{\s*display: flex;/)
  assert.match(drawerRule, /\.chat__scroll \{ padding: var\(--sp-4\); \}/)
  assert.match(drawerRule, /\.msg--assistant \.msg__main \{ max-width: 100%; \}/)
  assert.match(drawerRule, /\.msg__bubble \{ max-width: 88%; \}/)
  assert.doesNotMatch(drawerRule, /\.chat-side \{ display: none; \}/)
})
