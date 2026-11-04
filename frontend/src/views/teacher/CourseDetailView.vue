<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="router.back()">
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <h2 class="page-title">{{ course ? course.name : '课程管理' }}</h2>
        <p class="page-sub">维护课程知识点体系与教材资料</p>
      </div>
      <div class="page-head__actions">
        <el-button v-if="features.feature_course_share" @click="openShare">
          <el-icon><Share /></el-icon> 分享课程
        </el-button>
      </div>
    </div>

    <el-tabs v-model="tab">
      <!-- 知识点 -->
      <el-tab-pane label="知识点体系" name="kp">
        <div class="tab-body">
          <div class="filter-bar">
            <el-button type="primary" @click="kpDialog = true">
              <el-icon><Plus /></el-icon> 添加知识点
            </el-button>
            <el-button :loading="draftLoading" @click="triggerDraftUpload">
              <el-icon><MagicStick /></el-icon> 从目录生成
            </el-button>
            <input
              ref="draftInput"
              type="file"
              accept=".txt,.md,.docx,.xlsx"
              hidden
              @change="onDraftFile"
            />
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ knowledgePoints.length }} 个知识点</span>
          </div>

          <div class="panel">
            <el-table :data="knowledgePoints">
              <el-table-column prop="name" label="知识点" min-width="180" />
              <el-table-column label="上级知识点" width="180">
                <template #default="{ row }">
                  <span v-if="row.parent_id">{{ kpName(row.parent_id) }}</span>
                  <span v-else class="dim">—</span>
                </template>
              </el-table-column>
              <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
              <template #empty>
                <div class="empty-state">暂无知识点</div>
              </template>
            </el-table>
          </div>
        </div>
      </el-tab-pane>

      <!-- 教材与资料 -->
      <el-tab-pane label="教材与资料" name="materials">
        <div class="tab-body">
          <div class="filter-bar">
            <el-button type="primary" @click="openUpload">
              <el-icon><Upload /></el-icon> 上传资料
            </el-button>
            <span class="tip">支持 PDF / DOCX / PPTX / XLSX / TXT / MD / CSV / 代码文件；图片需开启识图</span>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ materials.length }} 份资料</span>
          </div>

          <div class="panel">
            <el-table :data="materials">
              <el-table-column prop="title" label="资料标题" min-width="200" />
              <el-table-column label="类型" width="120">
                <template #default="{ row }">
                  <el-tag :type="typeTag(row.type)" size="small" effect="light">{{ typeLabel(row.type) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="chunk_count" label="分块数" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.chunk_count > 0 ? 'success' : 'info'" size="small" effect="light">
                    {{ row.chunk_count || '未入库' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="解析" width="130">
                <template #default="{ row }">
                  <el-tooltip
                    :content="row.parse_error || ''"
                    :disabled="!row.parse_error"
                    placement="top"
                  >
                    <el-tag :type="parseTag(row)" size="small" effect="light">
                      {{ parseLabel(row) }}
                    </el-tag>
                  </el-tooltip>
                </template>
              </el-table-column>
              <el-table-column label="上传时间" width="180">
                <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="canRetryParse(row)" link type="primary"
                    @click="retryParse(row)"
                  >
                    重新解析
                  </el-button>
                </template>
              </el-table-column>
              <template #empty>
                <div class="empty-state">暂无教材资料</div>
              </template>
            </el-table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 添加知识点 -->
    <el-dialog v-model="kpDialog" title="添加知识点" width="480px">
      <el-form :model="kpForm" label-position="top">
        <el-form-item label="知识点名" required>
          <el-input v-model="kpForm.name" placeholder="如：二叉树遍历" />
        </el-form-item>
        <el-form-item label="上级知识点">
          <el-select v-model="kpForm.parentId" clearable style="width: 100%" placeholder="不选则为顶级知识点">
            <el-option v-for="kp in knowledgePoints" :key="kp.id" :label="kp.name" :value="kp.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="kpForm.description" type="textarea" :rows="3" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="kpDialog = false">取消</el-button>
        <el-button type="primary" :loading="kpLoading" @click="addKp">添加</el-button>
      </template>
    </el-dialog>

    <!-- 上传资料 -->
    <el-dialog v-model="uploadDialog" title="上传资料" width="480px">
      <el-form :model="uploadForm" label-position="top">
        <el-form-item label="资料类型" required>
          <el-select v-model="uploadForm.type" style="width: 100%">
            <el-option label="课件" value="courseware" />
            <el-option label="教学大纲" value="syllabus" />
            <el-option label="练习题" value="exercise" />
            <el-option label="面试资料" value="interview" />
          </el-select>
        </el-form-item>
        <el-form-item label="资料标题" required>
          <el-input v-model="uploadForm.title" placeholder="请输入资料标题" />
        </el-form-item>
        <el-form-item label="文件" required>
          <el-upload
            :show-file-list="true"
            :limit="1"
            :before-upload="beforeUpload"
            :http-request="doUpload"
            accept=".pdf,.txt,.md,.docx"
          >
            <el-button type="primary" size="small" :loading="uploading">
              <el-icon><Upload /></el-icon> 选择并上传
            </el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialog = false">关闭</el-button>
      </template>
    </el-dialog>
    <!-- 知识点草稿预览 -->
    <el-dialog v-model="draftVisible" title="知识点与大纲草稿" width="720px">
      <div v-if="draft" class="draft">
        <p class="draft__file">来源文件：{{ draft.filename }}</p>
        <el-checkbox v-model="applySyllabus">同时更新课程大纲</el-checkbox>
        <el-input
          v-if="applySyllabus"
          v-model="draftSyllabus"
          class="draft__syllabus"
          type="textarea"
          :rows="6"
        />
        <p class="draft__hint">勾选需要采纳的知识点；采纳后才会写入正式知识点体系，未采纳内容不会影响教学。</p>
        <el-tree
          ref="treeRef"
          :data="draftTree"
          show-checkbox
          node-key="path"
          :props="{ label: 'label', children: 'children' }"
          default-expand-all
        />
      </div>
      <template #footer>
        <el-button @click="discardDraft">丢弃草稿</el-button>
        <el-button @click="draftVisible = false">稍后处理</el-button>
        <el-button type="primary" :loading="adopting" @click="adoptSelected">采纳选中</el-button>
        <el-button type="success" :loading="adopting" @click="adoptAll">全部采纳</el-button>
      </template>
    </el-dialog>

    <!-- 分享课程 -->
    <el-dialog v-model="shareVisible" title="分享课程" width="620px">
      <el-form inline class="share-form">
        <el-form-item label="有效天数">
          <el-input-number v-model="shareForm.expires_days" :min="1" :max="365" />
        </el-form-item>
        <el-form-item label="可用次数">
          <el-input-number v-model="shareForm.max_uses" :min="1" :max="100" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="sharing" @click="createShare">生成教师课程码</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="shares" size="small" v-loading="shareLoading">
        <el-table-column label="教师课程码" width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="copyShare(row.code)">{{ row.code }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="有效期至" min-width="150">
          <template #default="{ row }">{{ formatTime(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column label="已用/次数" width="100">
          <template #default="{ row }">{{ row.used_count }}/{{ row.max_uses }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="shareTag(row.status)" size="small" effect="light">
              {{ shareLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button v-if="row.status === 'active'" link type="danger" @click="revokeShare(row)">撤销</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">还没有教师课程码，设置有效期后点击生成</div>
        </template>
      </el-table>
      <p class="share-hint">对方凭码复制为课程快照，只包含课程信息、知识点与资料元数据，不会带走本课程的学生、学情与作业数据。</p>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { courseApi } from '../../api/course'
import { teacherApi } from '../../api/teacher'
import { features, loadFeatures } from '../../stores/features'

const route = useRoute()
const router = useRouter()
const courseId = Number(route.params.id)

const loading = ref(true)
const course = ref(null)
const tab = ref('kp')
const knowledgePoints = ref([])
const materials = ref([])

const kpDialog = ref(false)
const kpLoading = ref(false)
const uploading = ref(false)
const kpForm = reactive({ name: '', description: '', parentId: null })

const uploadDialog = ref(false)
const uploadForm = reactive({ type: 'courseware', title: '' })

// ---------- 知识点草稿 ----------
const draftInput = ref()
const draftVisible = ref(false)
const draftLoading = ref(false)
const adopting = ref(false)
const draft = ref(null)
const draftTree = ref([])
const draftSyllabus = ref('')
const applySyllabus = ref(false)
const treeRef = ref()

// ---------- 课程分享 ----------
const shareVisible = ref(false)
const sharing = ref(false)
const shareLoading = ref(false)
const shares = ref([])
const shareForm = reactive({ expires_days: 7, max_uses: 1 })

const TYPE_LABELS = {
  courseware: '课件',
  syllabus: '教学大纲',
  exercise: '练习题',
  interview: '面试资料',
}

onMounted(() => {
  load()
  if (!features.loaded) loadFeatures()
})

async function load() {
  loading.value = true
  try {
    // 后端知识点/素材接口均直接返回数组
    const [c, kps, mats] = await Promise.all([
      courseApi.detail(courseId),
      courseApi.knowledgePoints(courseId),
      courseApi.materials(courseId),
    ])
    course.value = c
    knowledgePoints.value = Array.isArray(kps) ? kps : []
    materials.value = Array.isArray(mats) ? mats : []
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

function kpName(id) {
  return knowledgePoints.value.find((kp) => kp.id === id)?.name || `#${id}`
}

function typeLabel(t) {
  return TYPE_LABELS[t] || t || '—'
}

function typeTag(t) {
  return { courseware: '', syllabus: 'success', exercise: 'warning', interview: 'danger' }[t] || 'info'
}

function formatTime(t) {
  if (!t) return '—'
  return String(t).replace('T', ' ').slice(0, 19)
}

// ---------- 知识点草稿:上传 → 预览 → 选择性采纳 ----------

function triggerDraftUpload() {
  draftInput.value?.click()
}

async function onDraftFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  draftLoading.value = true
  try {
    const data = await teacherApi.createKpDraft(courseId, file)
    draft.value = data
    draftSyllabus.value = data.payload?.syllabus || ''
    applySyllabus.value = false
    draftTree.value = toTree(data.payload?.knowledge_points || [])
    draftVisible.value = true
  } catch { /* 拦截器已提示 */ } finally {
    draftLoading.value = false
  }
}

function toTree(nodes, prefix = '') {
  return (nodes || []).map((node, index) => {
    const path = prefix ? `${prefix}-${index}` : `${index}`
    const children = toTree(node.children || [], path)
    return {
      path,
      label: node.name,
      description: node.description,
      ...(children.length ? { children } : {}),
    }
  })
}

async function adoptSelected() {
  const paths = treeRef.value?.getCheckedKeys() || []
  if (!paths.length) return ElMessage.warning('请先勾选需要采纳的知识点')
  await adoptDraft({ paths, adopt_all: false })
}

async function adoptAll() {
  await adoptDraft({ adopt_all: true })
}

async function adoptDraft(payload) {
  adopting.value = true
  try {
    const res = await teacherApi.adoptKpDraft(draft.value.id, {
      ...payload,
      apply_syllabus: applySyllabus.value,
      syllabus: applySyllabus.value ? draftSyllabus.value : null,
    })
    const extra = res.skipped ? `，跳过重复 ${res.skipped} 个` : ''
    ElMessage.success(`已采纳 ${res.created} 个知识点${extra}`)
    draftVisible.value = false
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    adopting.value = false
  }
}

async function discardDraft() {
  try {
    await teacherApi.discardKpDraft(draft.value.id)
    draftVisible.value = false
    ElMessage.success('草稿已丢弃')
  } catch { /* 拦截器已提示 */ }
}

async function addKp() {
  if (!kpForm.name.trim()) return ElMessage.warning('请输入知识点名')
  kpLoading.value = true
  try {
    await courseApi.addKnowledgePoint(courseId, kpForm)
    ElMessage.success('知识点已添加')
    kpDialog.value = false
    Object.assign(kpForm, { name: '', description: '', parentId: null })
    load()
  } catch { /* 拦截器已提示 */ } finally {
    kpLoading.value = false
  }
}

// ---------- 课程分享 ----------

async function openShare() {
  shareVisible.value = true
  await loadShares()
}

async function loadShares() {
  shareLoading.value = true
  try {
    const rows = await teacherApi.shares(courseId)
    shares.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    shareLoading.value = false
  }
}

async function createShare() {
  try {
    await ElMessageBox.confirm('生成课程码后其他教师可复制本课程快照，确定生成？', '生成课程码', { type: 'warning' })
  } catch { return }
  sharing.value = true
  try {
    const res = await teacherApi.createShare(courseId, {
      expires_days: shareForm.expires_days,
      max_uses: shareForm.max_uses,
    }, true)
    ElMessage.success(`教师课程码已生成：${res.code}`)
    await loadShares()
  } catch { /* 拦截器已提示 */ } finally {
    sharing.value = false
  }
}

async function revokeShare(row) {
  try {
    await ElMessageBox.confirm('撤销后该课程码立即失效，确定撤销？', '撤销课程码', { type: 'warning' })
  } catch { return }
  try {
    await teacherApi.revokeShare(row.id, true)
    ElMessage.success('已撤销')
    await loadShares()
  } catch { /* 拦截器已提示 */ }
}

async function copyShare(code) {
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success('教师课程码已复制')
  } catch {
    ElMessage.warning(`请手动复制教师课程码：${code}`)
  }
}

function shareLabel(s) {
  return { active: '可用', expired: '已过期', exhausted: '已用完', revoked: '已撤销' }[s] || s
}

function shareTag(s) {
  return { active: 'success', expired: 'info', exhausted: 'warning', revoked: 'danger' }[s] || 'info'
}

function openUpload() {
  Object.assign(uploadForm, { type: 'courseware', title: '' })
  uploadDialog.value = true
}

function beforeUpload(file) {
  const allowed = [
    '.pdf', '.docx', '.pptx', '.xlsx', '.xlsm', '.txt', '.md', '.csv',
    '.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.sql', '.html',
    '.css', '.vue', '.json', '.xml', '.yml', '.yaml',
    '.png', '.jpg', '.jpeg', '.webp', '.bmp',
  ]
  const name = (file.name || '').toLowerCase()
  const ok = allowed.some((ext) => name.endsWith(ext))
  if (!ok) ElMessage.warning('不支持该文件格式，请上传文档、代码或图片')
  if (ok && !uploadForm.title.trim()) {
    uploadForm.title = file.name.replace(/\.[^.]+$/, '')
  }
  return ok
}

async function doUpload({ file }) {
  if (!uploadForm.title.trim()) return ElMessage.warning('请填写资料标题')
  uploading.value = true
  try {
    await courseApi.uploadMaterial(courseId, uploadForm.type, uploadForm.title, file)
    ElMessage.success('上传成功，正在后台解析与审核')
    uploadDialog.value = false
    load()
    setTimeout(load, 1500)
  } catch { /* 拦截器已提示 */ } finally {
    uploading.value = false
  }
}

// ---------- 素材解析状态 ----------

function parseLabel(row) {
  const status = row.parse_status
  if (status === 'done') return '已解析'
  if (status === 'processing') return `解析中 ${row.parse_progress || 0}%`
  if (status === 'pending') return '排队中'
  if (status === 'rejected') return '审核未通过'
  if (status === 'failed') return '解析失败'
  return row.chunk_count > 0 ? '已入库' : '未解析'
}

function parseTag(row) {
  if (row.parse_status === 'done') return 'success'
  if (row.parse_status === 'rejected' || row.parse_status === 'failed') return 'danger'
  if (row.parse_status) return 'warning'
  return 'info'
}

function canRetryParse(row) {
  return ['failed', 'rejected'].includes(row.parse_status)
    || (!row.parse_status && !row.chunk_count)
}

async function retryParse(row) {
  try {
    await courseApi.retryMaterialParse(courseId, row.id)
    ElMessage.success('已重新提交解析')
    load()
  } catch { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.tab-body { display: flex; flex-direction: column; gap: var(--sp-4); }
.tip { font-size: var(--fs-xs); color: var(--text-secondary); }
.draft__file {
  margin-bottom: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.draft__syllabus { margin: var(--sp-2) 0; }
.draft__hint {
  margin: var(--sp-3) 0 var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.dim { color: var(--text-placeholder); }
.share-form { margin-bottom: var(--sp-2); }
.share-hint { margin-top: var(--sp-3); font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
