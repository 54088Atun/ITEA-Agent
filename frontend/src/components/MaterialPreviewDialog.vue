<template>
  <el-dialog
    :model-value="modelValue"
    :title="material?.title || '资料预览'"
    width="min(880px, 92vw)"
    destroy-on-close
    @update:model-value="onVisibleChange"
    @closed="cleanup"
  >
    <div v-loading="loading" class="preview-body">
      <iframe
        v-if="kind === 'pdf' && objectUrl"
        :src="objectUrl"
        class="preview-frame"
        title="资料预览"
      ></iframe>
      <img
        v-else-if="kind === 'image' && objectUrl"
        :src="objectUrl"
        class="preview-image"
        alt="资料预览"
      />
      <pre v-else-if="text" class="preview-text">{{ text }}</pre>
      <StateBlock
        v-else
        state="empty"
        title="暂无可展示的内容"
        hint="可下载后用 Office / WPS 打开"
      />
    </div>
    <template #footer>
      <span class="preview-hint">{{ fileName }}</span>
      <el-button :loading="downloading" @click="download">下载</el-button>
      <el-button @click="onVisibleChange(false)">关闭</el-button>
      <el-button type="primary" :disabled="!objectUrl && !text" @click="openNewTab">
        新窗口打开
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { courseApi } from '../api/course'
import StateBlock from './StateBlock.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  courseId: { type: Number, required: true },
  material: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif']
const TEXT_EXTS = [
  'txt', 'md', 'csv', 'py', 'js', 'ts', 'jsx', 'tsx', 'java', 'c', 'cpp',
  'h', 'sql', 'html', 'css', 'vue', 'json', 'xml', 'yml', 'yaml', 'log', 'sh',
]

const loading = ref(false)
const downloading = ref(false)
const kind = ref('text')
const objectUrl = ref('')
const text = ref('')

const fileName = computed(() => {
  const path = props.material?.file_path || ''
  return path.split(/[\\/]/).pop() || props.material?.title || ''
})

watch(
  () => [props.modelValue, props.material?.id],
  ([visible]) => {
    if (visible && props.material) load()
    if (!visible) cleanup()
  },
)

onBeforeUnmount(cleanup)

function onVisibleChange(value) {
  emit('update:modelValue', value)
}

function cleanup() {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
  text.value = ''
}

function extOf() {
  const path = props.material?.file_path || props.material?.title || ''
  const match = String(path).match(/\.([a-z0-9]+)$/i)
  return match ? match[1].toLowerCase() : ''
}

async function load() {
  cleanup()
  loading.value = true
  const materialId = props.material.id
  const ext = extOf()
  try {
    if (TEXT_EXTS.includes(ext)) {
      const data = await courseApi.materialText(props.courseId, materialId)
      text.value = data?.text || ''
      kind.value = 'text'
      return
    }
    if (IMAGE_EXTS.includes(ext)) {
      const blob = await courseApi.materialPreviewBlob(props.courseId, materialId)
      objectUrl.value = URL.createObjectURL(blob)
      kind.value = 'image'
      return
    }
    if (ext === 'pdf') {
      const blob = await courseApi.materialPreviewBlob(props.courseId, materialId)
      objectUrl.value = URL.createObjectURL(blob)
      kind.value = 'pdf'
      return
    }
    // Office 文档优先转 PDF,呈现与 Word/Excel/PPT 一致的版式
    try {
      const blob = await courseApi.materialPreviewBlob(
        props.courseId, materialId, { render: 'pdf', silent: true },
      )
      objectUrl.value = URL.createObjectURL(blob)
      kind.value = 'pdf'
    } catch {
      const data = await courseApi.materialText(props.courseId, materialId)
      text.value = data?.text || ''
      kind.value = 'text'
    }
  } catch {
    try {
      const data = await courseApi.materialText(props.courseId, materialId)
      text.value = data?.text || ''
    } catch { text.value = '' }
    kind.value = 'text'
  } finally {
    loading.value = false
  }
}

async function download() {
  if (!props.material) return
  downloading.value = true
  try {
    const blob = await courseApi.materialDownloadBlob(props.courseId, props.material.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = fileName.value || props.material.title || 'courseware'
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10000)
    ElMessage.success('已开始下载')
  } catch { /* 拦截器已提示 */ } finally {
    downloading.value = false
  }
}

function openNewTab() {
  if (objectUrl.value) {
    window.open(objectUrl.value, '_blank', 'noopener')
    return
  }
  if (!text.value) return
  const url = URL.createObjectURL(new Blob([text.value], { type: 'text/plain;charset=utf-8' }))
  window.open(url, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
</script>

<style scoped>
.preview-body { min-height: 240px; }
.preview-frame { width: 100%; height: 68vh; border: 0; }
.preview-image { display: block; max-width: 100%; margin: 0 auto; }
.preview-text {
  max-height: 62vh;
  overflow: auto;
  margin: 0;
  padding: var(--sp-3);
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.preview-hint { margin-right: auto; font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
