<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">班级看板</h2>
        <p class="page-sub">查看课程整体学情、薄弱知识点与学生进度，并导出教学文档</p>
      </div>
      <div class="page-head__actions">
        <el-select v-model="courseId" placeholder="选择课程" filterable style="width: 200px" @change="load">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button :disabled="!courseId" @click="openLesson">
          <el-icon><MagicStick /></el-icon> AI 教案
        </el-button>
        <el-dropdown @command="doExport">
          <el-button type="primary" :loading="exporting">
            <el-icon><Download /></el-icon> 导出文档
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="lesson_plan">教案框架</el-dropdown-item>
              <el-dropdown-item command="report">班级学情报告</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <template v-if="loading && !report">
      <div class="panel">
        <SkeletonTable :rows="2" :cols="3" />
      </div>
      <div class="panel">
        <SkeletonTable :rows="6" :cols="4" />
      </div>
      <div class="panel">
        <SkeletonTable :rows="6" :cols="4" />
      </div>
    </template>
    <StateBlock v-else-if="error && !report" state="error" title="班级看板加载失败" @retry="load" />
    <template v-else-if="report">
      <!-- 概览（avg_progress 已是 0-100） -->
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi__label">平均进度</div>
          <div class="kpi__value"><CountUp :value="Math.round(report.avg_progress || 0)" /><span class="kpi__unit">%</span></div>
          <el-progress :percentage="clamp(report.avg_progress)" :show-text="false" :stroke-width="6" />
        </div>
        <div class="kpi">
          <div class="kpi__label">学生总数</div>
          <div class="kpi__value"><CountUp :value="report.student_count || report.students?.length || 0" /><span class="kpi__unit">人</span></div>
          <div class="kpi__hint">已加入本课程的学生</div>
        </div>
        <div class="kpi">
          <div class="kpi__label">薄弱知识点数</div>
          <div class="kpi__value kpi__value--weak"><CountUp :value="report.weak_points?.length || 0" /><span class="kpi__unit">个</span></div>
          <div class="kpi__hint">平均掌握度低于阈值</div>
        </div>
      </div>

      <!-- 薄弱知识点 TOP10 -->
      <div class="panel">
        <div class="panel__head">
          <h3 class="panel__title">薄弱知识点 TOP10</h3>
        </div>
        <el-table :data="report.weak_points || []">
          <el-table-column type="index" label="#" width="60" />
          <el-table-column prop="kp_name" label="知识点" min-width="180" />
          <el-table-column label="平均掌握度" width="220">
            <template #default="{ row }">
              <el-progress
                :percentage="clamp(row.avg_mastery)"
                :stroke-width="10"
                :class="['row-bar', `row-bar--${levelKey(row.avg_mastery)}`]"
              />
            </template>
          </el-table-column>
          <el-table-column prop="wrong_count" label="错题人次" width="110" />
          <template #empty>
            <StateBlock state="empty" title="暂无薄弱知识点" />
          </template>
        </el-table>
      </div>

      <!-- 学生简报 -->
      <div class="panel">
        <div class="panel__head">
          <h3 class="panel__title">学生简报</h3>
          <span class="panel__meta">共 {{ report.students?.length || 0 }} 名学生</span>
        </div>
        <el-table :data="report.students || []">
          <el-table-column prop="user_id" label="学生ID" width="100" />
          <el-table-column prop="name" label="姓名" width="140" />
          <el-table-column label="总体进度" width="220">
            <template #default="{ row }">
              <el-progress
                :percentage="clamp(row.overall_progress)"
                :stroke-width="10"
                :class="['row-bar', `row-bar--${levelKey(row.overall_progress)}`]"
              />
            </template>
          </el-table-column>
          <el-table-column prop="weak_count" label="薄弱知识点数" width="130" />
          <template #empty>
            <StateBlock state="empty" title="暂无学生数据" />
          </template>
        </el-table>
      </div>
    </template>

    <div v-else-if="!loading && !error" class="empty-state">选择课程后查看班级看板</div>

    <!-- AI 教案生成 -->
    <el-dialog v-model="lessonVisible" title="AI 教案生成" width="720px">
      <el-form inline class="lesson-form">
        <el-form-item label="章节">
          <el-input
            v-model="lessonForm.chapter"
            placeholder="选填，如：第三章 等价类划分"
            style="width: 260px"
          />
        </el-form-item>
        <el-form-item label="课时">
          <el-input-number v-model="lessonForm.hours" :min="1" :max="12" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="lessonLoading" @click="generateLesson">生成</el-button>
        </el-form-item>
      </el-form>
      <div class="lesson-out" v-loading="lessonLoading">
        {{ lessonText || '填写章节后点击生成，教案会在这里流式输出。' }}
      </div>
      <template #footer>
        <el-button @click="lessonVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { teacherApi, LESSON_PLAN_URL } from '../../api/teacher'
import { ssePost } from '../../utils/sse.js'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'
import CountUp from '../../components/CountUp.vue'

const loading = ref(false)
const error = ref(false)
const courses = ref([])
const courseId = ref(null)
const report = ref(null)
const exporting = ref(false)

// AI 教案:经 SSE 流式返回,渲染为纯文本保留排版
const lessonVisible = ref(false)
const lessonLoading = ref(false)
const lessonText = ref('')
const lessonForm = reactive({ chapter: '', hours: 2 })
let lessonController = null

onMounted(async () => {
  try {
    // /teacher/courses 直接返回数组
    const data = await teacherApi.courses()
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) {
      courseId.value = courses.value[0].id
      load()
    }
  } catch { /* 拦截器已提示 */ }
})

async function load() {
  if (!courseId.value) return
  error.value = false
  loading.value = true
  try {
    report.value = await teacherApi.classReport(courseId.value)
  } catch { error.value = true } finally {
    loading.value = false
  }
}

function clamp(v) {
  return Math.min(100, Math.max(0, Math.round(Number(v) || 0)))
}

function levelKey(v) {
  // 班级看板沿用 70 / 40 分档
  if (v >= 70) return 'good'
  if (v >= 40) return 'mid'
  return 'weak'
}

async function doExport(type) {
  if (!courseId.value) return ElMessage.warning('请先选择课程')
  exporting.value = true
  try {
    // type ∈ lesson_plan / preview_sheet / report，课程 ID 一并提交
    const data = await teacherApi.exportDoc(type, courseId.value, {
      course_name: report.value?.course_name,
      report: report.value,
      weak_points: report.value?.weak_points || [],
      students: report.value?.students || [],
    })
    if (data.file_url) {
      window.open(data.file_url, '_blank')
      ElMessage.success('文档已生成，正在下载')
    } else {
      ElMessage.warning('文档生成失败，请稍后重试')
    }
  } catch { /* 拦截器已提示 */ } finally {
    exporting.value = false
  }
}

function openLesson() {
  lessonText.value = ''
  lessonVisible.value = true
}

function generateLesson() {
  if (!courseId.value) return ElMessage.warning('请先选择课程')
  lessonController?.abort()
  lessonText.value = ''
  lessonLoading.value = true
  lessonController = ssePost(
    LESSON_PLAN_URL,
    {
      course_id: courseId.value,
      chapter: lessonForm.chapter.trim() || null,
      hours: lessonForm.hours || null,
    },
    {
      onEvent(evt) {
        if (evt.type === 'token') {
          lessonText.value += evt.data?.content || ''
        } else if (evt.type === 'reset') {
          lessonText.value = ''
        } else if (evt.type === 'error') {
          lessonText.value += `\n[生成失败] ${evt.data?.message || '请稍后重试'}`
        }
      },
      onDone() { lessonLoading.value = false },
      onError(err) {
        lessonLoading.value = false
        ElMessage.error(err?.message || '教案生成失败')
      },
    },
  )
}

onBeforeUnmount(() => {
  lessonController?.abort()
})
</script>

<style scoped>
.kpi__value--weak { color: var(--color-danger); }
.panel__meta { margin-left: auto; font-size: var(--fs-sm); color: var(--text-secondary); }
/* 进度条颜色交给 token，随深浅色主题实时切换 */
.row-bar--good :deep(.el-progress-bar__inner) { background: var(--chart-good); }
.row-bar--mid :deep(.el-progress-bar__inner) { background: var(--chart-mid); }
.row-bar--weak :deep(.el-progress-bar__inner) { background: var(--chart-weak); }

.lesson-form { margin-bottom: var(--sp-2); }
.lesson-out {
  min-height: 240px;
  max-height: 52vh;
  overflow: auto;
  padding: var(--sp-4);
  background: var(--bg-subtle);
  border-radius: var(--r-md);
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
