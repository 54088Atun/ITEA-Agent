/**
 * 联系我们页面默认文案
 * 后台保存的内容会通过 applyContactConfig 覆盖这里的字段
 */
import { reactive } from 'vue'

export const contact = reactive({
  eyebrow: '联系我们',
  title: '有事找我们，直接说',
  lead: '课程、账号、部署、数据合规，都有人负责。工作日的消息当天会有人看，紧急问题建议直接打电话。',

  channels: [
    {
      icon: 'Message',
      label: '邮箱',
      value: 'support@itea-agent.cn',
      hint: '工作日 24 小时内回复',
      href: 'mailto:support@itea-agent.cn',
    },
    {
      icon: 'Phone',
      label: '电话',
      value: '021-6588 0000',
      hint: '周一至周五 9:00–18:00',
      href: 'tel:02165880000',
    },
    {
      icon: 'Location',
      label: '办公室',
      value: '上海市杨浦区教学楼 A 座 402',
      hint: '来访请提前预约',
      href: '',
    },
    {
      icon: 'Clock',
      label: '服务时间',
      value: '周一至周五 9:00–18:00',
      hint: '法定节假日顺延',
      href: '',
    },
  ],

  departments: [
    {
      name: '教学支持',
      desc: '建课、班级、作业考试、学情看板使用问题',
      contact: 'teacher@itea-agent.cn',
    },
    {
      name: '学生支持',
      desc: '账号登录、错题复习、面试实训相关问题',
      contact: 'student@itea-agent.cn',
    },
    {
      name: '技术运维',
      desc: '校内部署、接口对接、模型与存储配置',
      contact: 'ops@itea-agent.cn',
    },
    {
      name: '数据与合规',
      desc: '内容分级、操作日志、数据删除与授权',
      contact: 'compliance@itea-agent.cn',
    },
  ],

  faqs: [
    {
      q: '学校想整体部署，从哪一步开始？',
      a: '先确认使用范围（学院或全校）、账号体系（对接统一认证还是独立账号）和部署位置（校内服务器或私有云）。把这三项发到 support@itea-agent.cn，我们会回一份部署清单和排期建议。',
    },
    {
      q: '学生账号登录不了怎么办？',
      a: '先确认账号是否被停用、密码是否需要重置。教师和管理员可以在对应页面处理；学生本人可以直接联系我们，说明姓名、学号和院系。',
    },
    {
      q: '平台里的数据会拿去训练模型吗？',
      a: '不会。教学数据不用于训练；录音转写完成后即删除，识图原图保留 30 天且本人可删，日志写入前会先做脱敏。',
    },
    {
      q: '反馈问题需要提供什么信息？',
      a: '说明发生时间、所在页面、操作步骤和期望结果；有报错截图或会话 ID 更好。我们会按操作日志定位，并在处理完成后回复。',
    },
  ],
})

function assignStrings(target, source, keys) {
  if (!source || typeof source !== 'object') return
  keys.forEach((key) => {
    if (typeof source[key] === 'string' && source[key].trim()) {
      target[key] = source[key]
    }
  })
}

function mergeList(target, source, keys) {
  if (!Array.isArray(source)) return
  const next = source.map((item, index) => {
    if (!item || typeof item !== 'object') return null
    const base = target[index] ? { ...target[index] } : {}
    keys.forEach((key) => {
      if (typeof item[key] === 'string') base[key] = item[key]
    })
    return base
  }).filter(Boolean)
  if (next.length) target.splice(0, target.length, ...next)
}

/** 合并后台保存的联系页内容；只接受已知字段 */
export function applyContactConfig(config) {
  if (!config || typeof config !== 'object') return

  assignStrings(contact, config, ['eyebrow', 'title', 'lead'])
  mergeList(contact.channels, config.channels, ['icon', 'label', 'value', 'hint', 'href'])
  mergeList(contact.departments, config.departments, ['name', 'desc', 'contact'])
  mergeList(contact.faqs, config.faqs, ['q', 'a'])
}

/** 内置默认值快照：后台“恢复默认”时使用 */
const CONTACT_DEFAULTS = JSON.parse(JSON.stringify({
  eyebrow: contact.eyebrow,
  title: contact.title,
  lead: contact.lead,
  channels: contact.channels,
  departments: contact.departments,
  faqs: contact.faqs,
}))

export function contactDefaults() {
  return JSON.parse(JSON.stringify(CONTACT_DEFAULTS))
}
