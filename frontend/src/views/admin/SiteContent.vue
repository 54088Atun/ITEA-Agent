<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">站点内容</h2>
        <p class="page-sub">首页与联系页的文案在这里维护，保存后访客刷新即可看到</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="previewHome"><el-icon><View /></el-icon> 预览首页</el-button>
        <el-button @click="previewContact"><el-icon><Service /></el-icon> 预览联系页</el-button>
        <el-button @click="load"><el-icon><Refresh /></el-icon> 重新加载</el-button>
        <el-button
          v-if="userStore.canAdminWrite"
          type="primary"
          :loading="saving"
          @click="save"
        >
          <el-icon><Check /></el-icon> 保存内容
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!userStore.canAdminWrite"
      type="warning" :closable="false" show-icon
      title="观察者仅可查看站点内容，修改请联系超级管理员或普通管理员。"
      class="tip-alert"
    />

    <SkeletonCard v-if="loading && !loaded" :rows="6" />
    <StateBlock
      v-else-if="loadError && !loaded"
      state="error"
      title="站点内容加载失败"
      action-label="重新加载"
      @retry="load"
    />
    <el-tabs v-else v-model="tab" v-loading="loading">
      <!-- ===== 首页 ===== -->
      <el-tab-pane label="首页" name="home">
        <div class="tab-body">
          <section class="panel">
            <div class="panel__head">
              <span class="panel__title">首屏文案</span>
              <span class="panel__hint">标题拆成两段，第二段用铜金色强调；按钮文案对应首屏两个 CTA</span>
            </div>
            <div class="panel__body form-grid">
              <label class="field field--full">
                <span>顶部小标签</span>
                <el-input v-model="home.hero.eyebrow" :disabled="readonly" maxlength="40" show-word-limit />
              </label>
              <label class="field">
                <span>标题前半句</span>
                <el-input v-model="home.hero.titleLead" :disabled="readonly" maxlength="30" show-word-limit />
              </label>
              <label class="field">
                <span>标题后半句</span>
                <el-input v-model="home.hero.titleAccent" :disabled="readonly" maxlength="30" show-word-limit />
              </label>
              <label class="field field--full">
                <span>导语</span>
                <el-input v-model="home.hero.lead" type="textarea" :rows="3" :disabled="readonly" maxlength="180" show-word-limit />
              </label>
              <label class="field field--full">
                <span>标题下补充说明</span>
                <el-input v-model="home.hero.note" :disabled="readonly" maxlength="40" />
              </label>
              <label class="field">
                <span>主按钮文案</span>
                <el-input v-model="home.hero.actions[0].label" :disabled="readonly" maxlength="10" show-word-limit />
              </label>
              <label class="field">
                <span>次按钮文案</span>
                <el-input v-model="home.hero.actions[1].label" :disabled="readonly" maxlength="10" show-word-limit />
              </label>
            </div>
          </section>

          <section class="panel">
            <div class="panel__head">
              <span class="panel__title">数据条</span>
              <span class="panel__hint">首屏下方的一行数字，最多 6 项</span>
            </div>
            <div class="panel__body">
              <div v-for="(item, index) in home.facts" :key="index" class="repeat-row">
                <el-input v-model="item.value" :disabled="readonly" placeholder="数值" class="repeat-row__num" />
                <el-input v-model="item.unit" :disabled="readonly" placeholder="单位" class="repeat-row__unit" />
                <el-input v-model="item.label" :disabled="readonly" placeholder="名称" />
                <el-input v-model="item.hint" :disabled="readonly" placeholder="补充说明" />
                <el-button
                  v-if="readonly === false"
                  link type="danger"
                  @click="home.facts.splice(index, 1)"
                >删除</el-button>
              </div>
              <el-button
                v-if="readonly === false && home.facts.length < 6"
                class="add-btn"
                @click="home.facts.push({ value: '', unit: '', label: '', hint: '' })"
              ><el-icon><Plus /></el-icon> 增加一项</el-button>
            </div>
          </section>

          <section class="panel">
            <div class="panel__head">
              <span class="panel__title">教学场景轮播</span>
              <span class="panel__hint">可上传图片，也可直接填写图片地址</span>
            </div>
            <div class="panel__body">
              <div v-for="(slide, index) in home.slides" :key="index" class="slide-card">
                <div class="slide-card__head">
                  <span>第 {{ index + 1 }} 张</span>
                  <span v-if="uploadingIndex === index" class="dim">图片上传中…</span>
                </div>
                <div class="slide-media">
                  <img
                    v-if="slide.image && !failedImages[index]"
                    :src="resolveAsset(slide.image)"
                    :alt="`第 ${index + 1} 张配图`"
                    class="slide-media__preview"
                    @error="failedImages[index] = true"
                  />
                  <div v-else class="slide-media__empty">
                    {{ slide.image ? '图片加载失败，可重新上传或换地址' : '暂无图片' }}
                  </div>
                  <div class="slide-media__body">
                    <label class="field">
                      <span>图片地址</span>
                      <el-input
                        v-model="slide.image"
                        :disabled="readonly"
                        placeholder="/static/site/home/xxx.png 或 https://..."
                        @input="failedImages[index] = false"
                      />
                    </label>
                    <div class="slide-media__actions">
                      <el-button
                        v-if="readonly === false"
                        size="small"
                        :loading="uploadingIndex === index"
                        @click="pickImage(index)"
                      >
                        <el-icon><Upload /></el-icon> 上传图片
                      </el-button>
                      <span class="dim">PNG / JPG / WEBP，不超过 5MB</span>
                    </div>
                  </div>
                </div>
                <div class="form-grid">
                  <label class="field">
                    <span>标签</span>
                    <el-input v-model="slide.tag" :disabled="readonly" maxlength="10" />
                  </label>
                  <label class="field">
                    <span>要点</span>
                    <el-input v-model="slide.metric" :disabled="readonly" maxlength="20" />
                  </label>
                  <label class="field field--full">
                    <span>标题</span>
                    <el-input v-model="slide.title" :disabled="readonly" maxlength="40" />
                  </label>
                  <label class="field field--full">
                    <span>说明</span>
                    <el-input v-model="slide.desc" type="textarea" :rows="2" :disabled="readonly" maxlength="120" show-word-limit />
                  </label>
                </div>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel__head"><span class="panel__title">收尾与页脚</span></div>
            <div class="panel__body form-grid">
              <label class="field">
                <span>收尾标题</span>
                <el-input v-model="home.closing.title" :disabled="readonly" maxlength="30" />
              </label>
              <label class="field">
                <span>收尾说明</span>
                <el-input v-model="home.closing.desc" :disabled="readonly" maxlength="80" />
              </label>
              <label class="field">
                <span>品牌名</span>
                <el-input v-model="home.footer.brand" :disabled="readonly" maxlength="30" />
              </label>
              <label class="field">
                <span>页脚一句话</span>
                <el-input v-model="home.footer.desc" :disabled="readonly" maxlength="60" />
              </label>
              <label class="field field--full">
                <span>版权信息</span>
                <el-input v-model="home.footer.copyright" :disabled="readonly" maxlength="80" />
              </label>
            </div>
          </section>
        </div>
      </el-tab-pane>

      <!-- ===== 联系我们 ===== -->
      <el-tab-pane label="联系我们" name="contact">
        <div class="tab-body">
          <section class="panel">
            <div class="panel__head"><span class="panel__title">页面标题</span></div>
            <div class="panel__body form-grid">
              <label class="field">
                <span>顶部小标签</span>
                <el-input v-model="contact.eyebrow" :disabled="readonly" maxlength="20" />
              </label>
              <label class="field">
                <span>标题</span>
                <el-input v-model="contact.title" :disabled="readonly" maxlength="30" />
              </label>
              <label class="field field--full">
                <span>导语</span>
                <el-input v-model="contact.lead" type="textarea" :rows="3" :disabled="readonly" maxlength="180" show-word-limit />
              </label>
            </div>
          </section>

          <section class="panel">
            <div class="panel__head">
              <span class="panel__title">联系方式</span>
              <span class="panel__hint">显示在标题下方的四张卡片</span>
            </div>
            <div class="panel__body">
              <div v-for="(item, index) in contact.channels" :key="index" class="repeat-card">
                <div class="repeat-card__head">
                  <span>第 {{ index + 1 }} 项</span>
                  <el-button v-if="readonly === false" link type="danger" @click="contact.channels.splice(index, 1)">删除</el-button>
                </div>
                <div class="form-grid">
                  <label class="field">
                    <span>图标</span>
                    <el-select v-model="item.icon" :disabled="readonly">
                      <el-option v-for="icon in iconOptions" :key="icon.value" :label="icon.label" :value="icon.value" />
                    </el-select>
                  </label>
                  <label class="field">
                    <span>名称</span>
                    <el-input v-model="item.label" :disabled="readonly" maxlength="10" />
                  </label>
                  <label class="field">
                    <span>展示内容</span>
                    <el-input v-model="item.value" :disabled="readonly" maxlength="60" />
                  </label>
                  <label class="field">
                    <span>补充说明</span>
                    <el-input v-model="item.hint" :disabled="readonly" maxlength="40" />
                  </label>
                  <label class="field field--full">
                    <span>跳转链接（可选，如 mailto: / tel:）</span>
                    <el-input v-model="item.href" :disabled="readonly" maxlength="120" />
                  </label>
                </div>
              </div>
              <el-button v-if="readonly === false" class="add-btn" @click="contact.channels.push({ icon: 'Message', label: '', value: '', hint: '', href: '' })">
                <el-icon><Plus /></el-icon> 增加联系方式
              </el-button>
            </div>
          </section>

          <section class="panel">
            <div class="panel__head"><span class="panel__title">对接部门</span></div>
            <div class="panel__body">
              <div v-for="(item, index) in contact.departments" :key="index" class="repeat-card">
                <div class="repeat-card__head">
                  <span>第 {{ index + 1 }} 个部门</span>
                  <el-button v-if="readonly === false" link type="danger" @click="contact.departments.splice(index, 1)">删除</el-button>
                </div>
                <div class="form-grid">
                  <label class="field">
                    <span>部门名称</span>
                    <el-input v-model="item.name" :disabled="readonly" maxlength="20" />
                  </label>
                  <label class="field">
                    <span>联系邮箱</span>
                    <el-input v-model="item.contact" :disabled="readonly" maxlength="80" />
                  </label>
                  <label class="field field--full">
                    <span>负责范围</span>
                    <el-input v-model="item.desc" :disabled="readonly" maxlength="120" />
                  </label>
                </div>
              </div>
              <el-button v-if="readonly === false" class="add-btn" @click="contact.departments.push({ name: '', desc: '', contact: '' })">
                <el-icon><Plus /></el-icon> 增加部门
              </el-button>
            </div>
          </section>

          <section class="panel">
            <div class="panel__head"><span class="panel__title">常见问题</span></div>
            <div class="panel__body">
              <div v-for="(item, index) in contact.faqs" :key="index" class="repeat-card">
                <div class="repeat-card__head">
                  <span>第 {{ index + 1 }} 条</span>
                  <el-button v-if="readonly === false" link type="danger" @click="contact.faqs.splice(index, 1)">删除</el-button>
                </div>
                <label class="field field--full">
                  <span>问题</span>
                  <el-input v-model="item.q" :disabled="readonly" maxlength="80" />
                </label>
                <label class="field field--full">
                  <span>回答</span>
                  <el-input v-model="item.a" type="textarea" :rows="3" :disabled="readonly" maxlength="400" show-word-limit />
                </label>
              </div>
              <el-button v-if="readonly === false" class="add-btn" @click="contact.faqs.push({ q: '', a: '' })">
                <el-icon><Plus /></el-icon> 增加问题
              </el-button>
            </div>
          </section>
        </div>
      </el-tab-pane>
    </el-tabs>

    <input
      ref="imageInput"
      type="file"
      accept="image/png,image/jpeg,image/webp"
      hidden
      @change="onImagePick"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../../api/admin'
import { resolveAsset } from '../../utils/asset.js'
import { useUserStore } from '../../stores/user'
import { useSiteStore } from '../../stores/site'
import { homeDefaults } from '../home/content'
import { contactDefaults } from '../contact/content'
import SkeletonCard from '../../components/SkeletonCard.vue'
import StateBlock from '../../components/StateBlock.vue'

const userStore = useUserStore()
const siteStore = useSiteStore()

const tab = ref('home')
const loading = ref(false)
const saving = ref(false)
const loadError = ref(false)
const loaded = ref(false)
const home = ref(homeDefaults())
const contact = ref(contactDefaults())
const imageInput = ref(null)
const imageTarget = ref(-1)
const uploadingIndex = ref(-1)
const failedImages = ref({})

const readonly = computed(() => !userStore.canAdminWrite)

const iconOptions = [
  { label: '消息 / 邮箱', value: 'Message' },
  { label: '电话', value: 'Phone' },
  { label: '位置', value: 'Location' },
  { label: '时间', value: 'Clock' },
]

onMounted(load)

function pickStrings(source, base) {
  const out = { ...base }
  if (source && typeof source === 'object') {
    Object.keys(base).forEach((key) => {
      if (typeof source[key] === 'string') out[key] = source[key]
    })
  }
  return out
}

function mergeRows(baseRows, savedRows, keys) {
  if (!Array.isArray(savedRows)) return baseRows.map((row) => ({ ...row }))
  return savedRows.map((row, index) => {
    const out = { ...(baseRows[index] || {}) }
    keys.forEach((key) => {
      if (typeof row?.[key] === 'string') out[key] = row[key]
    })
    return out
  })
}

function buildHome(saved) {
  const base = homeDefaults()
  if (!saved || typeof saved !== 'object') return base
  const hero = pickStrings(saved.hero, base.hero)
  const savedActions = Array.isArray(saved.hero?.actions) ? saved.hero.actions : []
  hero.actions = base.hero.actions.map((action, index) => ({
    ...action,
    label: typeof savedActions[index]?.label === 'string' && savedActions[index].label.trim()
      ? savedActions[index].label
      : action.label,
  }))
  return {
    hero,
    facts: mergeRows(base.facts, saved.facts, ['value', 'unit', 'label', 'hint']),
    slides: mergeRows(base.slides, saved.slides, ['tag', 'title', 'desc', 'metric', 'image']),
    closing: pickStrings(saved.closing, base.closing),
    footer: pickStrings(saved.footer, base.footer),
  }
}

function buildContact(saved) {
  const base = contactDefaults()
  if (!saved || typeof saved !== 'object') return base
  return {
    eyebrow: typeof saved.eyebrow === 'string' ? saved.eyebrow : base.eyebrow,
    title: typeof saved.title === 'string' ? saved.title : base.title,
    lead: typeof saved.lead === 'string' ? saved.lead : base.lead,
    channels: mergeRows(base.channels, saved.channels, ['icon', 'label', 'value', 'hint', 'href']),
    departments: mergeRows(base.departments, saved.departments, ['name', 'desc', 'contact']),
    faqs: mergeRows(base.faqs, saved.faqs, ['q', 'a']),
  }
}

async function load() {
  loadError.value = false
  loading.value = true
  try {
    const data = await adminApi.siteContent()
    home.value = buildHome(data?.home)
    contact.value = buildContact(data?.contact)
    loaded.value = true
  } catch {
    loadError.value = true /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function validate() {
  const hero = home.value.hero
  if (!hero.titleLead.trim() || !hero.titleAccent.trim()) {
    return '请填写首页标题的前后两句'
  }
  if (!home.value.closing.title.trim()) return '请填写首页收尾标题'
  if (!home.value.hero.actions[0]?.label?.trim() || !home.value.hero.actions[1]?.label?.trim()) {
    return '请填写首屏两个按钮文案'
  }
  if (!contact.value.title.trim()) return '请填写联系页标题'
  if (!contact.value.channels.length) return '联系页至少保留一项联系方式'
  return ''
}

async function save() {
  const error = validate()
  if (error) return ElMessage.warning(error)

  let payload
  try {
    payload = JSON.parse(JSON.stringify({
      home: home.value,
      contact: contact.value,
    }))
  } catch {
    return ElMessage.error('内容格式有误，请检查后重试')
  }

  saving.value = true
  try {
    await adminApi.saveSiteContent(payload)
    await siteStore.reload()
    ElMessage.success('站点内容已保存')
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

function pickImage(index) {
  if (readonly.value) return
  imageTarget.value = index
  imageInput.value?.click()
}

async function onImagePick(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  const index = imageTarget.value
  if (!file || index < 0) return

  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    return ElMessage.warning('仅支持 PNG、JPG、WEBP 图片')
  }
  if (file.size > 5 * 1024 * 1024) {
    return ElMessage.warning('图片不能超过 5MB')
  }

  uploadingIndex.value = index
  try {
    const data = await adminApi.uploadSiteImage(file)
    if (data?.url && home.value.slides[index]) {
      home.value.slides[index].image = data.url
      failedImages.value[index] = false
      ElMessage.success('图片已上传，保存内容后生效')
    }
  } catch { /* 拦截器已提示 */ } finally {
    uploadingIndex.value = -1
  }
}

function previewHome() {
  window.open('/', '_blank', 'noopener')
}

function previewContact() {
  window.open('/contact', '_blank', 'noopener')
}
</script>

<style scoped>
.tip-alert {
  margin-bottom: var(--sp-3);
  border-radius: var(--r-sm);
}

.tab-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding-top: var(--sp-2);
}

.panel__head {
  gap: var(--sp-2);
}

.panel__hint {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-4);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.field--full {
  grid-column: 1 / -1;
}

.repeat-row {
  display: grid;
  grid-template-columns: 90px 70px minmax(0, 1fr) minmax(0, 1.4fr) auto;
  gap: var(--sp-2);
  align-items: center;
  padding: var(--sp-2) 0;
  border-bottom: 1px dashed var(--border);
}

.repeat-row:last-of-type {
  border-bottom: none;
}

.repeat-card {
  padding: var(--sp-3) 0 var(--sp-4);
  border-bottom: 1px dashed var(--border);
}

.repeat-card:last-of-type {
  border-bottom: none;
}

.repeat-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--sp-3);
  font-size: var(--fs-xs);
  letter-spacing: 0.06em;
  color: var(--text-placeholder);
}

.slide-card {
  padding: var(--sp-3) 0 var(--sp-4);
  border-bottom: 1px dashed var(--border);
}

.slide-card:last-of-type {
  border-bottom: none;
}

.slide-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--sp-3);
  font-size: var(--fs-xs);
  letter-spacing: 0.06em;
  color: var(--text-placeholder);
}

.slide-media {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-4);
  margin-bottom: var(--sp-3);
}

.slide-media__preview,
.slide-media__empty {
  width: 180px;
  flex: 0 0 180px;
  aspect-ratio: 16 / 10;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-subtle);
}

.slide-media__preview {
  object-fit: cover;
}

.slide-media__empty {
  display: grid;
  place-items: center;
  border-style: dashed;
  border-color: var(--border-strong);
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.slide-media__body {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--sp-2);
}

.slide-media__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.dim {
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.add-btn {
  margin-top: var(--sp-3);
}

@media (max-width: 767px) {
  .form-grid {
    grid-template-columns: 1fr;
  }

  .slide-media {
    flex-direction: column;
  }

  .slide-media__preview,
  .slide-media__empty {
    width: 100%;
    flex: 0 0 auto;
  }

  .repeat-row {
    grid-template-columns: 1fr 1fr;
  }

  .repeat-row :deep(.el-input) {
    grid-column: span 1;
  }
}
</style>
