<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">课程资料</h2>
        <p class="page-sub">查看并下载老师上传的课件、教学大纲与练习题</p>
      </div>
      <div class="page-head__actions">
        <el-select
          v-model="courseId"
          placeholder="选择课程"
          filterable
          style="width: 220px"
          @change="loadMaterials"
        >
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </div>
    </div>

    <div v-if="loadingCourses" class="panel">
      <SkeletonTable :rows="4" :cols="4" />
    </div>
    <StateBlock v-else-if="!courses.length" state="empty" title="还没有可查看的课程" hint="先使用课程码加入班级" />
    <div v-else class="panel">
      <SkeletonTable v-if="loadingMaterials && !materials.length" :rows="5" :cols="4" />
      <StateBlock v-else-if="error" state="error" title="资料加载失败" @retry="loadMaterials" />
      <el-table v-else :data="materials" v-loading="loadingMaterials">
        <el-table-column label="资料标题" min-width="220">
          <template #default="{ row }">
            <el-button link type="primary" @click="openPreview(row)">{{ row.title }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="typeTag(row.type)" size="small" effect="light">{{ typeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="openPreview(row)">查看</el-button>
            <el-button link type="success" :loading="downloadingId === row.id" @click="download(row)">
              下载
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <StateBlock state="empty" title="该课程暂无资料" />
        </template>
      </el-table>
    </div>

    <MaterialPreviewDialog
      v-model="previewVisible"
      :course-id="courseId"
      :material="previewMaterial"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { courseApi } from '../../api/course'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'
import MaterialPreviewDialog from '../../components/MaterialPreviewDialog.vue'

const TYPE_LABELS = {
  courseware: '课件',
  syllabus: '教学大纲',
  exercise: '练习题',
  interview: '面试资料',
}

const courses = ref([])
const courseId = ref(null)
const materials = ref([])
const loadingCourses = ref(true)
const loadingMaterials = ref(false)
const error = ref(false)
const previewVisible = ref(false)
const previewMaterial = ref(null)
const downloadingId = ref(null)

onMounted(loadCourses)

async function loadCourses() {
  loadingCourses.value = true
  try {
    const data = await courseApi.list()
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) {
      courseId.value = courses.value[0].id
      await loadMaterials()
    }
  } catch { /* 拦截器已提示 */ } finally {
    loadingCourses.value = false
  }
}

async function loadMaterials() {
  if (!courseId.value) return
  error.value = false
  loadingMaterials.value = true
  try {
    const data = await courseApi.materials(courseId.value)
    materials.value = Array.isArray(data) ? data : []
  } catch {
    error.value = true
  } finally {
    loadingMaterials.value = false
  }
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type || '资料'
}

function typeTag(type) {
  return { courseware: '', syllabus: 'success', exercise: 'warning', interview: 'danger' }[type] || 'info'
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

function openPreview(row) {
  previewMaterial.value = row
  previewVisible.value = true
}

async function download(row) {
  downloadingId.value = row.id
  try {
    const blob = await courseApi.materialDownloadBlob(courseId.value, row.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    const path = row.file_path || ''
    link.download = path.split(/[\\/]/).pop() || row.title || 'courseware'
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 10000)
    ElMessage.success('已开始下载')
  } catch { /* 拦截器已提示 */ } finally {
    downloadingId.value = null
  }
}
</script>

<style scoped>
.panel { min-height: 200px; }
</style>
