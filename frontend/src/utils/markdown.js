import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/vs2015.css'

// 配置 marked:代码高亮 + 换行转 <br>
marked.setOptions({
  breaks: true,
  gfm: true,
})

// 自定义 renderer:代码块高亮 + 图表占位
const renderer = new marked.Renderer()
renderer.code = function (codeOrToken, lang) {
  // 兼容 marked 旧签名 (code, lang) 与新签名 ({ text, lang })
  const raw = typeof codeOrToken === 'string'
    ? codeOrToken
    : (codeOrToken?.text || '')
  const rawLang = typeof codeOrToken === 'string'
    ? lang
    : (codeOrToken?.lang || '')
  const language = (rawLang || '').match(/^[\w-]+/)?.[0] || 'plaintext'

  // 图表块:交给前端绘制 SVG,避免引入 ECharts 重依赖
  if (language === 'chart') {
    return `<div class="chart-slot" data-chart="${encodeURIComponent(raw)}"></div>`
  }

  let highlighted
  try {
    highlighted = language !== 'plaintext' && hljs.getLanguage(language)
      ? hljs.highlight(raw, { language }).value
      : hljs.highlightAuto(raw).value
  } catch {
    highlighted = raw
  }
  return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
}
marked.use({ renderer })

/**
 * 将 Markdown 文本渲染为安全的 HTML
 * @param {string} text Markdown 原文
 * @returns {string} 经 DOMPurify 消毒的 HTML
 */
export function renderMarkdown(text) {
  if (!text) return ''
  const raw = marked.parse(text)
  return DOMPurify.sanitize(raw)
}

/**
 * 高亮 [AI 辅助参考] 标识,便于前端样式强调
 */
export function highlightAiTag(html) {
  return html.replace(
    /\[AI 辅助参考[^\]]*\]/g,
    (m) => `<span class="ai-tag">${m}</span>`
  )
}