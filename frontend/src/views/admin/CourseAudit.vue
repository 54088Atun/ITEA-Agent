<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">课程审核</h2>
        <p class="page-sub">课程上架前的资质与内容审核，同时维护课程素材</p>
      </div>
      <div class="page-head__actions">
        <span v-if="tab === 'audit'" class="page-head__stat">待审核 {{ pendingCount }} 门</span>
      </div>
    </div>

    <el-tabs v-model="tab">
      <!-- 课程审核 -->
      <el-tab-pane label="课程审核" name="audit">
        <div class="tab-body">
          <div class="filter-bar">
            <DebouncedInput v-model="filters.keyword" placeholder="课程名 / 课程代码" clearable style="width: 200px" @keyup.enter="reload" @debounce="reload" />
            <el-input v-model="filters.semester" placeholder="学期" clearable style="width: 130px" @keyup.enter="reload" />
            <el-select v-model="filters.audit_status" placeholder="全部审核状态" clearable style="width: 160px">
              <el-option label="待审核" value="pending" />
              <el-option label="已通过" value="approved" />
              <el-option label="已驳回" value="rejected" />
            </el-select>
            <el-button type="primary" @click="reload"><el-icon><Search /></el-icon> 查询</el-button>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ total }} 门课程</span>
          </div>

          <transition name="fade">
            <div v-if="selectedIds.length" class="batch-bar">
              <span class="batch-bar__text">已选 {{ selectedIds.length }} 门</span>
              <el-button size="small" @click="clearSelection">取消选择</el-button>
              <el-button size="small" type="success" plain @click="batchAudit('approved')">批量通过</el-button>
              <el-button size="small" type="danger" plain @click="batchAudit('rejected')">批量驳回</el-button>
            </div>
          </transition>

          <div class="panel">
            <SkeletonTable v-if="loading && !courses.length" :rows="8" :cols="6" />
            <StateBlock v-else-if="error" state="error" @retry="load" />
            <el-table
              v-else
              ref="tableRef"
              :data="courses"
              v-loading="loading"
              row-key="id"
              @selection-change="onSelectionChange"
            >
              <el-table-column v-if="userStore.canAdminWrite" type="selection" width="46" />
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="name" label="课程名称" min-width="180" />
              <el-table-column prop="code" label="代码" width="120" />
              <el-table-column prop="teacher_name" label="授课教师" width="120" />
              <el-table-column prop="semester" label="学期" width="120" />
              <el-table-column prop="syllabus" label="课程简介" min-width="220" show-overflow-tooltip />
              <el-table-column label="审核状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="auditTag(row.audit_status)" size="small" effect="light">{{ auditLabel(row.audit_status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="创建时间" width="180">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column v-if="userStore.canAdminWrite" label="操作" width="230" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openCourseOverview(row)">概览</el-button>
                  <el-button
                    link type="success" :disabled="row.audit_status === 'approved'"
                    @click="audit(row, 'approved')"
                  >通过</el-button>
                  <el-button
                    link type="danger" :disabled="row.audit_status === 'rejected'"
                    @click="audit(row, 'rejected')"
                  >驳回</el-button>
                  <el-button
                    v-if="row.audit_status !== 'pending'"
                    link type="warning" @click="audit(row, 'pending')"
                  >待审</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <StateBlock
                  state="empty"
                  title="没有符合条件的课程"
                  hint="调整审核状态、学期或关键词后重试"
                />
              </template>
            </el-table>

            <div class="pager">
              <el-pagination
                v-model:current-page="page"
                v-model:page-size="size"
                :total="total"
                :page-sizes="[10, 20, 50]"
                layout="total, sizes, prev, pager, next"
                @current-change="load"
                @size-change="reload"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 素材管理 -->
      <el-tab-pane label="素材管理" name="materials">
        <div class="tab-body">
          <div class="filter-bar">
            <el-select v-model="materialCourseId" placeholder="全部课程" clearable filterable style="width: 240px">
              <el-option v-for="c in courseOptions" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
            <el-button type="primary" @click="reloadMaterials"><el-icon><Search /></el-icon> 查询</el-button>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ materialTotal }} 份素材</span>
          </div>

          <div class="panel">
            <SkeletonTable v-if="materialLoading && !materials.length" :rows="6" :cols="5" />
            <StateBlock
              v-else-if="materialError"
              state="error"
              title="素材加载失败"
              @retry="loadMaterials"
            />
            <el-table v-else :data="materials">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="course_id" label="课程ID" width="90" />
              <el-table-column prop="title" label="资料标题" min-width="200" />
              <el-table-column label="类型" width="110">
                <template #default="{ row }">
                  <el-tag size="small" effect="light">{{ typeLabel(row.type) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="chunk_count" label="分块数" width="90" />
              <el-table-column label="上传时间" width="180">
                <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
              </el-table-column>
              <el-table-column v-if="userStore.canAdminWrite" label="操作" width="100" fixed="right">
                <template #default="{ row }">
                  <el-button link type="danger" @click="removeMaterial(row)">删除</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <StateBlock state="empty" title="暂无课程素材" />
              </template>
            </el-table>

            <div class="pager">
              <el-pagination
                v-model:current-page="materialPage"
                v-model:page-size="materialSize"
                :total="materialTotal"
                :page-sizes="[10, 20, 50]"
                layout="total, sizes, prev, pager, next"
                @current-change="loadMaterials"
                @size-change="reloadMaterials"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 课程概览 -->
    <el-drawer
      v-model="overviewVisible"
      :title="`课程概览 · ${overviewData?.course?.name || ''}`"
      size="640px"
    >
      <div v-loading="overviewLoading" class="ov-body">
        <template v-if="overviewData">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="课程 ID">{{ overviewData.course.id }}</el-descriptions-item>
            <el-descriptions-item label="课程代码">{{ overviewData.course.code }}</el-descriptions-item>
            <el-descriptions-item label="学期">{{ overviewData.course.semester || '—' }}</el-descriptions-item>
            <el-descriptions-item label="审核状态">{{ auditLabel(overviewData.course.audit_status) }}</el-descriptions-item>
            <el-descriptions-item label="授课教师">
              {{ overviewData.teacher?.name || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="教师邮箱">{{ overviewData.teacher?.email || '—' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatTime(overviewData.course.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="归档 / 删除">
              {{ overviewData.course.archived ? '已归档' : '未归档' }} /
              {{ overviewData.course.deleted ? '已删除' : '正常' }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="ov-stats">
            <div class="ov-stat"><span>资料</span><b>{{ overviewData.materials.total }}</b></div>
            <div class="ov-stat"><span>知识点</span><b>{{ overviewData.knowledge_points }}</b></div>
            <div class="ov-stat"><span>班级</span><b>{{ overviewData.classes.total }}</b></div>
            <div class="ov-stat"><span>班级学生</span><b>{{ overviewData.classes.students }}</b></div>
            <div class="ov-stat"><span>选课人数</span><b>{{ overviewData.classes.enrollments }}</b></div>
          </div>

          <section class="ov-section">
            <h4 class="ov-title">审核历史（{{ overviewData.audit_history.length }}）</h4>
            <el-table :data="overviewData.audit_history" size="small" empty-text="暂无审核记录">
              <el-table-column prop="action" label="动作" width="140" />
              <el-table-column prop="admin_name" label="操作人" width="120" />
              <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip />
              <el-table-column label="时间" width="150">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '../../api/admin'
import { useUserStore } from '../../stores/user'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'
import DebouncedInput from '../../components/DebouncedInput.vue'

const userStore = useUserStore()

const tab = ref('audit')

// ---------- 课程审核 ----------
const loading = ref(false)
const error = ref(false)
const courses = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const filters = reactive({ keyword: '', semester: '', audit_status: '' })

const tableRef = ref()
const selectedIds = ref([])
const pendingCount = computed(() => courses.value.filter((c) => c.audit_status === 'pending').length)

// 课程概览
const overviewVisible = ref(false)
const overviewLoading = ref(false)
const overviewData = ref(null)

// ---------- 素材管理 ----------
const materialLoading = ref(false)
const materialError = ref(false)
const materials = ref([])
const materialTotal = ref(0)
const materialPage = ref(1)
const materialSize = ref(20)
const materialCourseId = ref(null)
const courseOptions = ref([])

onMounted(async () => {
  await Promise.all([load(), loadCourseOptions()])
})

async function load() {
  loading.value = true
  error.value = false
  try {
    const data = await adminApi.courses({
      page: page.value,
      size: size.value,
      audit_status: filters.audit_status || undefined,
      semester: filters.semester || undefined,
      keyword: filters.keyword || undefined,
    })
    courses.value = data.items || []
    total.value = data.total || 0
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function onSelectionChange(rows) {
  selectedIds.value = rows.map((r) => r.id)
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selectedIds.value = []
}

async function loadCourseOptions() {
  try {
    const data = await adminApi.courses({ page: 1, size: 100 })
    courseOptions.value = data.items || []
  } catch { /* 拦截器已提示 */ }
}

async function audit(row, status) {
  try {
    await ElMessageBox.confirm(
      `确认将课程「${row.name}」标记为${auditLabel(status)}?`,
      '课程审核',
      { type: 'warning' }
    )
  } catch { return }
  try {
    await adminApi.auditCourse(row.id, status)
    ElMessage.success('审核状态已更新')
    load()
  } catch { /* 拦截器已提示 */ }
}

/** 批量审核：先 dry_run 预演影响范围，确认后一次性执行并写汇总审计 */
async function batchAudit(status) {
  const ids = [...selectedIds.value]
  if (!ids.length) return

  let preview
  try {
    preview = await adminApi.batchAuditCourses(ids, status, true)
  } catch { return }

  const affected = preview.affected || []
  const skipped = preview.skipped || []
  const failed = preview.failed || []
  if (!affected.length) {
    ElMessage.warning(`没有可变更的课程（跳过 ${skipped.length} 门，失败 ${failed.length} 门）`)
    clearSelection()
    load()
    return
  }

  const lines = [`将把 ${affected.length} 门课程标记为${auditLabel(status)}`]
  if (skipped.length) lines.push(`跳过 ${skipped.length} 门：${skipped[0].reason}`)
  if (failed.length) lines.push(`失败 ${failed.length} 门：${failed[0].reason}`)
  try {
    await ElMessageBox.confirm(lines.join('；'), '批量审核预演', { type: 'warning' })
  } catch { return }

  try {
    const result = await adminApi.batchAuditCourses(ids, status, false)
    const ok = (result.affected || []).length
    const skip = (result.skipped || []).length
    const fail = (result.failed || []).length
    if (skip || fail) {
      ElMessage.warning(`已处理 ${ok} 门，跳过 ${skip} 门，失败 ${fail} 门`)
    } else {
      ElMessage.success(`已处理 ${ok} 门课程`)
    }
    clearSelection()
    load()
  } catch { /* 拦截器已提示 */ }
}

function auditLabel(s) {
  return { pending: '待审核', approved: '已通过', rejected: '已驳回' }[s] || s
}
function auditTag(s) {
  return { pending: 'warning', approved: 'success', rejected: 'danger' }[s] || 'info'
}

// ---------- 素材 ----------
async function loadMaterials() {
  materialError.value = false
  materialLoading.value = true
  try {
    const data = await adminApi.materials({
      page: materialPage.value,
      size: materialSize.value,
      course_id: materialCourseId.value || undefined,
    })
    materials.value = data.items || []
    materialTotal.value = data.total || 0
  } catch { materialError.value = true } finally {
    materialLoading.value = false
  }
}

function reloadMaterials() {
  materialPage.value = 1
  loadMaterials()
}

async function removeMaterial(row) {
  try {
    await ElMessageBox.confirm(`确认删除素材「${row.title}」?`, '提示', { type: 'warning' })
  } catch { return }
  try {
    await adminApi.deleteMaterial(row.id)
    ElMessage.success('已删除')
    loadMaterials()
  } catch { /* 拦截器已提示 */ }
}

// 首次切到素材页时加载
watch(tab, (v) => {
  if (v === 'materials' && !materials.value.length) loadMaterials()
})

function typeLabel(t) {
  return { courseware: '课件', syllabus: '教学大纲', exercise: '练习题', interview: '面试资料' }[t] || t
}

function formatTime(t) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

/** 课程概览：课程/教师/规模/审核历史一次取齐 */
async function openCourseOverview(row) {
  overviewData.value = null
  overviewVisible.value = true
  overviewLoading.value = true
  try {
    overviewData.value = await adminApi.courseOverview(row.id)
  } catch { /* 拦截器已提示 */ } finally {
    overviewLoading.value = false
  }
}
</script>

<style scoped>
.tab-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding-top: var(--sp-2);
}

.page-head__stat {
  font-size: var(--fs-sm);
  color: var(--color-warning);
  background: var(--color-warning-soft);
  border-radius: var(--r-pill);
  padding: var(--sp-1) var(--sp-3);
}

.filter-bar__count {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  background: var(--color-primary-wash);
  border: 1px solid var(--brand-100);
  border-radius: var(--r-md);
}
.batch-bar__text {
  font-size: var(--fs-sm);
  color: var(--color-primary);
  font-weight: 600;
  margin-right: var(--sp-2);
}

.panel :deep(.el-table__inner-wrapper::before) { display: none; }

.pager {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--border);
}

/* 课程概览抽屉 */
.ov-body { display: flex; flex-direction: column; gap: var(--sp-4); min-height: 120px; }
.ov-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: var(--sp-2);
}
.ov-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-3);
  background: var(--bg-subtle);
  border-radius: var(--r-md);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.ov-stat b { font-size: var(--fs-lg); color: var(--text-primary); }
.ov-section { display: flex; flex-direction: column; gap: var(--sp-2); }
.ov-title {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-primary);
}
</style>
