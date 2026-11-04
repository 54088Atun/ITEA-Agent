import { marked } from 'marked'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/vs2015.css'

// 素材预览/导出文件等链接在新窗口打开,避免点击后打断对话
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

// 配置 marked:代码高亮 + 换行转 <br>
marked.setOptions({
  breaks: true,
  gfm: true,
})

function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function plainCode(code, language) {
  let highlighted
  try {
    highlighted = language !== 'plaintext' && hljs.getLanguage(language)
      ? hljs.highlight(code, { language }).value
      : hljs.highlightAuto(code).value
  } catch {
    highlighted = escapeHtml(code)
  }
  return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`
}

/** 图表数据转可复制表格，保证无 JS 环境也能读到数值 */
function chartTable(spec) {
  const labels = Array.isArray(spec.labels) ? spec.labels : []
  const values = Array.isArray(spec.values) ? spec.values : []
  const rows = labels.map((label, i) => (
    `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(values[i] ?? '')}</td></tr>`
  )).join('')
  return `<details class="rich-data">`
    + `<summary>图表数据（可复制）</summary>`
    + `<table><thead><tr><th>项目</th><th>数值</th></tr></thead><tbody>${rows}</tbody></table>`
    + `</details>`
}

/** 代码 diff：逐行着色，保留空行高度，便于阅读补丁 */
function diffHtml(raw) {
  const lines = String(raw ?? '').split('\n')
  const rows = lines.map((line) => {
    let cls = 'is-ctx'
    if (/^(diff --git|index |new file mode|deleted file mode|similarity index|rename (from|to))/.test(line)) {
      cls = 'is-meta'
    } else if (/^(\+\+\+|---)(\s|$)/.test(line)) {
      cls = 'is-file'
    } else if (line.startsWith('@@')) {
      cls = 'is-hunk'
    } else if (line.startsWith('+')) {
      cls = 'is-add'
    } else if (line.startsWith('-')) {
      cls = 'is-del'
    }
    // 空行统一输出一个空格，避免折叠导致行号错位
    const text = line === '' ? ' ' : line
    return `<span class="diff-line ${cls}">${escapeHtml(text)}</span>`
  }).join('')
  return `<pre class="code-diff"><code>${rows}</code></pre>`
}

/** 时间线块：直接输出静态 HTML，无需前端脚本 */
function timelineHtml(raw) {
  let data
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  const items = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : null)
  if (!items || !items.length) return null
  const lis = items.map((item) => {
    const time = escapeHtml(item?.time ?? item?.date ?? '')
    const title = escapeHtml(item?.title ?? '')
    const desc = escapeHtml(item?.desc ?? item?.description ?? '')
    return `<li class="timeline__item">`
      + `<span class="timeline__dot" aria-hidden="true"></span>`
      + `<div class="timeline__body">`
      + `<div class="timeline__head">`
      + (time ? `<span class="timeline__time">${time}</span>` : '')
      + (title ? `<span class="timeline__title">${title}</span>` : '')
      + `</div>`
      + (desc ? `<p class="timeline__desc">${desc}</p>` : '')
      + `</div></li>`
  }).join('')
  return `<ol class="timeline">${lis}</ol>`
}

// 自定义 renderer:代码块高亮 + 富媒体占位
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
    let spec
    try {
      spec = JSON.parse(raw)
    } catch {
      spec = null
    }
    if (!spec || !Array.isArray(spec.labels) || !Array.isArray(spec.values)) {
      return plainCode(raw, language)
    }
    return `<div class="chart-slot" data-chart="${encodeURIComponent(raw)}"></div>`
      + chartTable(spec)
  }

  // Mermaid 图:先输出源码兜底,前端懒加载渲染为 SVG
  if (language === 'mermaid') {
    return `<div class="mermaid-slot" data-mermaid="${encodeURIComponent(raw)}">`
      + `<pre class="rich-fallback"><code>${escapeHtml(raw)}</code></pre>`
      + `</div>`
  }

  // 时间线:静态 HTML,流式结束即为最终形态
  if (language === 'timeline') {
    const html = timelineHtml(raw)
    if (html) return html
    return plainCode(raw, language)
  }

  // 代码 diff:逐行着色,便于阅读补丁
  if (language === 'diff' || language === 'patch') {
    return diffHtml(raw)
  }

  return plainCode(raw, language)
}
marked.use({ renderer })

// ---------- KaTeX 公式占位 ----------
// 只输出占位,KaTeX 由前端按需懒加载,避免首屏体积膨胀;无 JS 时仍显示原始 TeX。

function mathSlot(tex, display) {
  const text = display ? `$$${tex}$$` : `$${tex}$`
  return `<${display ? 'div' : 'span'} class="math-slot${display ? ' math-slot--block' : ''}"`
    + ` data-tex="${encodeURIComponent(tex)}" data-display="${display ? '1' : '0'}">`
    + `${escapeHtml(text)}`
    + `</${display ? 'div' : 'span'}>`
}

const blockMath = {
  name: 'blockMath',
  level: 'block',
  start(src) {
    return src.indexOf('$$')
  },
  tokenizer(src) {
    const match = /^\$\$\n?([\s\S]+?)\n?\$\$(?:\n+|$)/.exec(src)
    if (!match || !match[1].trim()) return undefined
    return { type: 'blockMath', raw: match[0], text: match[1].trim() }
  },
  renderer(token) {
    return mathSlot(token.text, true)
  },
}

const inlineMath = {
  name: 'inlineMath',
  level: 'inline',
  start(src) {
    const index = src.indexOf('$')
    return index < 0 ? undefined : index
  },
  tokenizer(src) {
    // 单个 $...$，要求两端非空白、无换行，避免误伤金额与普通文本
    const match = /^\$(?!\$)([^\s$][^$\n]*?[^\s$]|[^\s$])\$(?!\$)/.exec(src)
    if (!match) return undefined
    const tex = match[1]
    if (!/[\\^_=+\-*/(){}0-9a-zA-Z]/.test(tex)) return undefined
    return { type: 'inlineMath', raw: match[0], text: tex }
  },
  renderer(token) {
    return mathSlot(token.text, false)
  },
}

marked.use({ extensions: [blockMath, inlineMath] })

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
