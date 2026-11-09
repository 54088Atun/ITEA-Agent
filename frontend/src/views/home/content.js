/**
 * 公开首页文案与结构化内容
 * 集中在此文件，便于后续调整文案而不改动模板
 *
 * 写作口径：像老师在介绍自己的课，少用术语和排比，不用"赋能/闭环/链路"这类词
 *
 * 文案对象用 reactive 包裹：后台保存的站点内容会在运行时合并进来，
 * 页面无需刷新即可使用新文案。
 */
import { reactive } from 'vue'

export const nav = {
  links: [
    { label: '教学场景', href: '#showcase' },
    { label: '功能', href: '#capabilities' },
    { label: '老师与学生', href: '#roles' },
    { label: '数据与权限', href: '#trust' },
    { label: '常见问题', href: '#faq' },
    { label: '联系我们', to: '/contact' },
  ],
  login: { label: '登录', to: '/login' },
  cta: { label: '免费试用', to: '/login?mode=register' },
}

export const hero = reactive({
  eyebrow: '给高校老师和学生的教学助手',
  titleLead: '课程、作业和学情，',
  titleAccent: '放在一个地方。',
  lead: '老师在这里建课、发作业、看班级情况；学生在这里提问、改错题、练面试。有课程资料时，回答会标出内容来自哪份讲义、第几页；没有资料时会明确说明。',
  actions: [
    { label: '教师入口', to: '/login?role=teacher&mode=register', primary: true },
    { label: '学生入口', to: '/login?role=student&mode=register', primary: false },
  ],
  note: '校内账号可以直接登录',
  features: ['回答标来源', '操作先确认', '只看自己的课'],
  preview: {
    course: '数据结构 · 助教答疑',
    level: '信息级别：内部',
    question: '为什么 Dijkstra 不能处理负权边？',
    answer: [
      { text: 'Dijkstra 有一个前提：已经确定的最短距离，后面不会再变小。边权都是非负数时才成立。' },
      { text: '有负权边时，一条更长的路可能过一会儿又变短，已经出队的点得重新放回队列。' },
      { text: '所以负权图一般改用 Bellman-Ford，多花一点时间，但不会算错。' },
    ],
    sourceLabel: '参考来源',
    source: '数据结构讲义 · 第 12 页',
    aiTag: 'AI 辅助参考',
    approval: {
      title: '写操作待确认',
      action: '发布作业《最短路径练习》',
      meta: '发布后学生马上能看到',
      confirm: '确认',
      cancel: '取消',
    },
  },
})

export const facts = reactive([
  { value: '4', unit: '级', label: '内容分级', hint: '公开、内部、敏感、机密' },
  { value: '12', unit: '类', label: '操作要确认', hint: '发布、关闭、批改都在内' },
  { value: '有据可查', unit: '', label: '回答标来源', hint: '引用课程资料时标注文件与片段' },
  { value: '按需', unit: '', label: '多模态可配置', hint: '识图/语音按部署能力开启' },
])

export const roles = reactive([
  {
    key: 'teacher',
    name: '老师',
    tagline: '备课、出题、批改、看学情，本来要在四个地方做。',
    points: [
      '讲义传上来，知识点先列成草稿，合适的再收进课程',
      '作业和考试先给批改建议，老师确认后才算分',
      '按课程或按班看掌握情况，下次课讲什么心里有数',
    ],
    to: '/login?role=teacher&mode=register',
    linkLabel: '进入教师入口',
    tone: 'brand',
  },
  {
    key: 'student',
    name: '学生',
    tagline: '想问的时候没人可问，错了也不知道错在哪。',
    points: [
      '随时提问，回答下面标了来自哪份讲义',
      '做错的题自动进错题本，隔几天再练一次',
      '模拟面试按四个方面打分，知道差在哪',
    ],
    to: '/login?role=student&mode=register',
    linkLabel: '进入学生入口',
    tone: 'paper',
  },
])

/**
 * 首页轮播：图片由文生图接口生成，prompt 在此统一维护
 * 采用 encodeURIComponent 拼接，避免手写编码出错
 */
const showcaseImage = (prompt) =>
  `https://trae-api-cn.mchost.guru/api/ide/v1/tool_text_to_image?prompt=${encodeURIComponent(prompt)}&image_size=landscape_16_9`

export const showcase = reactive({
  eyebrow: '教学里的日常',
  title: '这些事，每周都在发生',
  desc: '从备课到课后复盘，下面四件事大概占了老师一半的时间。',
  slides: [
    {
      tag: '备课',
      icon: 'Notebook',
      title: '讲义传上去，知识点先列成草稿',
      desc: '系统把知识点列出来，老师看着改。合适的收进课程，不合适的直接丢掉。',
      metric: '先草稿，再采纳',
      alt: '现代大学教室里，教师与学生在自然光下讨论课程内容',
      image: showcaseImage(
        'editorial photograph of a modern university classroom in China, teacher and students discussing course material at a wooden table, large windows with soft daylight, shallow depth of field, calm indigo and warm brass tones, professional education photography, no text',
      ),
    },
    {
      tag: '答疑',
      icon: 'ChatDotRound',
      title: '学生问的问题，先查这门课',
      desc: '有课程资料时，它会翻讲义和做题记录再回答，并标注来源；没有资料时会明确说明。',
      metric: '有资料才标来源',
      alt: '学生在笔记本上查看助教回答，引用资料时底部标注来源',
      image: showcaseImage(
        'editorial photograph of a university student studying with a laptop showing a tutoring chat interface, textbooks and notes on a desk, warm desk lamp light, shallow depth of field, calm navy and cream palette, realistic, no readable text',
      ),
    },
    {
      tag: '学情',
      icon: 'DataAnalysis',
      title: '哪个知识点没掌握，一个班也能单独看',
      desc: '按课程看整体，也可以只看一个班。两个班的数据不会混在一起。',
      metric: '可以只看一个班',
      alt: '教师在教室里查看投影上的学情页面，学生在座位上听讲',
      image: showcaseImage(
        'editorial photograph of a university teacher reviewing a data dashboard projected in a classroom, students seated in the foreground, soft ambient light, muted blue and warm gold tones, professional education photography, no readable text',
      ),
    },
    {
      tag: '复习',
      icon: 'Microphone',
      title: '错过的题，过几天再练一次',
      desc: '做错的题会进错题本，按记忆规律排好下次练习的时间，不用学生自己记。',
      metric: '按记忆规律复习',
      alt: '学生在安静的自习室使用耳机练习口语，桌面上有笔记与平板',
      image: showcaseImage(
        'editorial photograph of a student practicing speaking with headphones in a quiet university study room, notebook and tablet on the desk, soft window light, calm blue and warm neutral tones, realistic education photography, no text',
      ),
    },
  ],
})

export const flow = reactive({
  title: '一个问题，回答之前要做四件事',
  desc: '它不会凭空作答。每一步都留下记录，出了问题能查。',
  steps: [
    {
      key: 'ask',
      index: '01',
      title: '提问',
      summary: '文字、图片、语音都行',
      detail: '图片先认字，再看图里大概在讲什么；语音在本机转成文字。这些内容只当作题目，不会被当成指令执行。',
      sample: '拍一张手写题 → 认出题干和公式',
      icon: 'ChatDotRound',
    },
    {
      key: 'fetch',
      index: '02',
      title: '查资料',
      summary: '先翻课程和做题记录',
      detail: '它去查这门课的讲义、你的做题记录和复习计划。不是你选的课，查不到。',
      sample: '看「数据结构」的掌握情况 → 发现最短路径这一章偏弱',
      icon: 'Connection',
    },
    {
      key: 'judge',
      index: '03',
      title: '判断',
      summary: '该拒绝就拒绝，该问就问',
      detail: '作业还没截止时问答案，它会改成讲思路；发布作业、确认成绩这类操作，会先弹出来问你要不要做。',
      sample: '作业没截止 → 只讲思路，不给标准答案',
      icon: 'Lock',
    },
    {
      key: 'answer',
      index: '04',
      title: '回答',
      summary: '边写边显示，引用资料时标来源',
      detail: '答案一边生成一边显示，有课程资料时附上参考来源。断网了可以回来接着看，重新问也不会重复记录。',
      sample: '给出解析 → 有资料时附来源片段 → 标注 AI 辅助参考',
      icon: 'Document',
    },
  ],
})

export const capabilities = reactive([
  {
    icon: 'Notebook',
    title: '课程与知识点',
    desc: '讲义上传后整理成知识点草稿，老师挑着收，不合适就丢掉。',
    tag: '先草稿，再采纳',
  },
  {
    icon: 'Document',
    title: '作业与考试',
    desc: '出题、发布、截止、补交都在这里。批改先给建议，老师确认后才计分。',
    tag: '老师确认才算分',
  },
  {
    icon: 'DataAnalysis',
    title: '班级与学情',
    desc: '按课程看掌握情况，也可以只看一个班，数据不会混在一起。',
    tag: '分班看',
  },
  {
    icon: 'Picture',
    title: '图片与语音',
    desc: '部署开启识图/语音后，可传图、粘贴截图或直接说话；未开启时入口会自动禁用。',
    tag: '按部署能力',
  },
  {
    icon: 'Connection',
    title: '多位助教协同',
    desc: '学生可以让辅导、复盘、面试几位助教配合；老师还能加上教案和学情分析。',
    tag: '按身份开放',
  },
  {
    icon: 'Microphone',
    title: '模拟面试',
    desc: '限时作答，事后从专业知识、逻辑表达、岗位匹配、沟通应答四方面给分。',
    tag: '四方面打分',
  },
])

export const trust = reactive({
  eyebrow: '数据与权限',
  title: '能看什么，事先定好',
  desc: '教学数据涉及学生隐私，所以先把谁能看、看多久、怎么查定下来。',
  data: [
    { title: '内容分四级', desc: '公开、内部、敏感、机密。每个身份能看到的上限不同，单个会话也能调整。' },
    { title: '录音不留', desc: '录音只在转文字时用一下，转完就删，不进数据库。' },
    { title: '图片存 30 天', desc: '识图的原图保留 30 天，本人可以随时查看和删除。' },
    { title: '日志先脱敏', desc: '密钥不出服务器，报错和请求信息写进日志前，先去掉敏感内容。' },
  ],
  ai: [
    { title: '动手前先问', desc: '发布、关闭、确认成绩等 12 类操作，没确认就不执行。' },
    { title: '每个回答有出处', desc: '答案下面标参考来源和页码，导出的文档也带同样的标注。' },
    { title: '不属于你的课查不到', desc: '课程范围和可用功能都要先校验，没有权限就不调用。' },
    { title: '用量有上限', desc: '识图次数、录音时长、单次大小都有限额，可以按身份适当放宽。' },
  ],
})

export const scenes = reactive([
  {
    title: '开学前，把课搭起来',
    steps: ['上传讲义，整理知识点', '建班，把课程码发给学生', '布置第一次作业'],
  },
  {
    title: '学期中，作业和考试',
    steps: ['选课程和发放班级', '批改建议出来，老师确认', '错题自动进学生的复习计划'],
  },
  {
    title: '期末，看结果',
    steps: ['按课程或按班看掌握情况', '找出几个共同薄弱点', '带着数据准备下一轮'],
  },
])

export const faqs = reactive([
  {
    q: '和直接用聊天工具有什么不一样？',
    a: '聊天工具不知道你教哪门课、班里谁没交作业。它会先去查这些数据，有资料时在回答下面标出来源；发布作业、确认成绩这类操作，会先让你确认。',
  },
  {
    q: '学校要单独部署吗？',
    a: '老师的课程默认只有自己能看到，学生能不能看到由班级和选课决定。可以按学校的账号体系对接，也可以独立部署。',
  },
  {
    q: '学生数据会拿去训练模型吗？',
    a: '不会。教学数据不用于训练。录音转完文字就删，识图原图保留 30 天、本人可删，日志写之前先脱敏。',
  },
  {
    q: '能传哪些文件？',
    a: 'PDF、Word、PPT、Excel、TXT、Markdown、CSV 和常见代码文件；图片支持 PNG、JPG、WEBP、BMP。其他格式会直接告诉你支持哪些。',
  },
  {
    q: '模型出问题或者断网怎么办？',
    a: '每个环节都有超时和兜底。识图失败还能手动输入，描述失败不影响认字，对话断了可以回来接着看答案。',
  },
  {
    q: '老师能不让它替学生写作业吗？',
    a: '能。作业或考试没截止时，学生问答案，它会改成讲思路，不给标准答案；截止或关闭之后正常回答。',
  },
])

export const closing = reactive({
  title: '先在一门课上用起来',
  desc: '从建课、发作业、看学情开始跑通，觉得顺手了再开更多功能。',
  actions: [
    { label: '现在开始', to: '/login?mode=register', primary: true },
    { label: '预约演示', to: '/login', primary: false },
  ],
})

export const footer = reactive({
  brand: 'ITEA-Agent',
  desc: '给高校老师和学生的教学助手',
  columns: [
    {
      title: '产品',
      links: [
        { label: '教学场景', href: '#showcase' },
        { label: '功能', href: '#capabilities' },
        { label: '老师与学生', href: '#roles' },
      ],
    },
    {
      title: '资源',
      links: [
        { label: '常见问题', href: '#faq' },
        { label: '数据与权限', href: '#trust' },
        { label: '联系我们', to: '/contact' },
        { label: '登录平台', to: '/login' },
      ],
    },
    {
      title: '数据',
      links: [
        { label: '内容分级说明', href: '#trust' },
        { label: '图片保留期限', href: '#trust' },
        { label: '操作记录', href: '#trust' },
      ],
    },
  ],
  copyright: '© 2026 ITEA-Agent · 校内教学使用',
})

/* ===== 后台可配置内容 ===== */

function assignStrings(target, source, keys) {
  if (!source || typeof source !== 'object') return
  keys.forEach((key) => {
    if (typeof source[key] === 'string' && source[key].trim()) {
      target[key] = source[key]
    }
  })
}

/** 用同一位置的默认项补齐缺失字段，避免后台只保存了部分内容时出现空白 */
function mergeList(target, source, keys, max = Infinity) {
  if (!Array.isArray(source)) return
  const next = source.slice(0, max).map((item, index) => {
    const base = target[index] ? { ...target[index] } : {}
    if (!item || typeof item !== 'object') return null
    keys.forEach((key) => {
      if (typeof item[key] === 'string') base[key] = item[key]
    })
    return base
  }).filter(Boolean)
  if (next.length) target.splice(0, target.length, ...next)
}

/**
 * 合并后台保存的首页内容；只接受已知字段，未知字段忽略
 * 传入空对象时保持内置文案不变
 */
export function applyHomeConfig(config) {
  if (!config || typeof config !== 'object') return

  assignStrings(hero, config.hero, ['eyebrow', 'titleLead', 'titleAccent', 'lead', 'note'])
  // CTA 按钮文案：只接受已知字段，多余项忽略
  if (Array.isArray(config.hero?.actions)) {
    config.hero.actions.slice(0, hero.actions.length).forEach((item, index) => {
      if (item && typeof item.label === 'string' && item.label.trim()) {
        hero.actions[index].label = item.label
      }
    })
  }
  mergeList(facts, config.facts, ['value', 'unit', 'label', 'hint'], 6)

  if (Array.isArray(config.slides)) {
    const next = config.slides.slice(0, showcase.slides.length).map((item, index) => {
      const base = showcase.slides[index] ? { ...showcase.slides[index] } : null
      if (!base || !item || typeof item !== 'object') return null
      ;['tag', 'title', 'desc', 'metric', 'image'].forEach((key) => {
        if (typeof item[key] === 'string') base[key] = item[key]
      })
      return base
    }).filter(Boolean)
    if (next.length) showcase.slides.splice(0, showcase.slides.length, ...next)
  }

  assignStrings(closing, config.closing, ['title', 'desc'])
  assignStrings(footer, config.footer, ['brand', 'desc', 'copyright'])
}

/** 内置默认值快照：后台“恢复默认”时使用，不受运行时合并影响 */
const HOME_DEFAULTS = JSON.parse(JSON.stringify({
  hero: {
    eyebrow: hero.eyebrow,
    titleLead: hero.titleLead,
    titleAccent: hero.titleAccent,
    lead: hero.lead,
    note: hero.note,
    actions: hero.actions.map(({ label }) => ({ label })),
  },
  facts,
  slides: showcase.slides.map(({ tag, title, desc, metric, image }) => ({
    tag, title, desc, metric, image,
  })),
  closing: { title: closing.title, desc: closing.desc },
  footer: { brand: footer.brand, desc: footer.desc, copyright: footer.copyright },
}))

export function homeDefaults() {
  return JSON.parse(JSON.stringify(HOME_DEFAULTS))
}
