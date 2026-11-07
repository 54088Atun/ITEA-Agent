<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">错题本</h2>
        <p class="page-sub">按知识点归类的错题记录，可结合遗忘曲线安排复习</p>
      </div>
      <div class="page-head__actions">
        <el-select v-model="courseId" placeholder="选择课程" filterable style="width: 220px" @change="onCourseChange">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button @click="load" :disabled="!courseId">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <div v-if="!courseId" class="panel">
      <div class="empty-state">请先在右上角选择一门课程</div>
    </div>

    <div v-else-if="error" class="panel">
      <StateBlock state="error" @retry="onCourseChange" />
    </div>

    <template v-else>
      <!-- 空态:没有错题时由 Agent 按科目生成练习 -->
      <div v-if="!records.length && !loading" class="panel">
        <div class="empty-state">
          <span>本课程还没有错题记录，可以让助手按课程知识点生成一组练习</span>
          <el-button type="primary" :loading="generating" @click="generate">
            <el-icon><MagicStick /></el-icon> 生成练习
          </el-button>
        </div>
      </div>

      <!-- 摘要：数量 / 覆盖知识点 / 错因分布 -->
      <div class="kpi-grid">
        <div class="kpi">
          <div class="kpi__label">错题总数</div>
          <div class="kpi__value">{{ records.length }}<span class="kpi__unit">道</span></div>
          <div class="kpi__hint">本课程累计记录</div>
        </div>
        <div class="kpi">
          <div class="kpi__label">涉及知识点</div>
          <div class="kpi__value">{{ kpCount }}<span class="kpi__unit">个</span></div>
          <div class="kpi__hint">已归类到具体知识点</div>
        </div>
        <div class="kpi">
          <div class="kpi__label">待归类</div>
          <div class="kpi__value kpi__value--muted">{{ unclassified }}<span class="kpi__unit">道</span></div>
          <div class="kpi__hint">建议在助教对话中补充知识点</div>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">错题清单</span>
          <span class="panel__meta">点击题目可查看完整内容</span>
        </div>
        <SkeletonTable v-if="loading && !records.length" :rows="6" :cols="5" />
        <el-table v-else :data="records" stripe class="wrong-table">
          <el-table-column label="题目内容" min-width="340">
            <template #default="{ row }">
              <div class="question-text" @click="expand(row)">{{ row.question_content }}</div>
            </template>
          </el-table-column>
          <el-table-column label="知识点" width="180">
            <template #default="{ row }">
              <el-tag type="warning" size="small" effect="light">{{ kpName(row.kp_id) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="错误类型" width="120">
            <template #default="{ row }">
              <el-tag :type="errorTypeColor(row.error_type)" size="small" effect="light">{{ row.error_type || '未分类' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="记录时间" width="170">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" :fixed="isNarrow ? false : 'right'">
            <template #default="{ row }">
              <el-button link type="primary" @click="expand(row)">查看</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <StateBlock
              state="empty"
              title="本课程还没有错题记录"
              hint="做错的题目会自动收进来"
            />
          </template>
        </el-table>
      </div>
    </template>

    <el-dialog v-model="dialogVisible" title="错题详情" width="600px">
      <template v-if="current">
        <div class="dialog-section">
          <div class="dialog-label">题目内容</div>
          <div class="dialog-body md-body" v-html="renderMarkdown(current.question_content)"></div>
        </div>
        <div class="dialog-section">
          <div class="dialog-label">关联知识点</div>
          <el-tag type="warning" effect="light">{{ kpName(current.kp_id) }}</el-tag>
          <el-tag v-if="current.error_type" :type="errorTypeColor(current.error_type)" effect="light" style="margin-left: 8px">
            {{ current.error_type }}
          </el-tag>
        </div>
        <el-alert type="info" :closable="false" style="margin-top: 12px">
          想要深入分析这道错题?请前往「课程助教」粘贴题目内容,AI 助教会引导你理清思路。
        </el-alert>
      </template>
    </el-dialog>

    <!-- 生成练习 -->
    <el-dialog v-model="practiceVisible" title="按课程生成练习" width="680px">
      <div v-if="practiceRecommendation" class="practice-recommendation">
        <div class="dialog-label">推荐理由</div>
        <p class="practice-recommendation__reason">
          {{ practiceRecommendation.reason || '课程基础推荐' }}
        </p>
        <div v-if="practiceRecommendation.record_refs?.length" class="practice-references">
          <div
            v-for="record in practiceRecommendation.record_refs"
            :key="`${record.type}-${record.id}`"
            class="practice-reference"
          >
            <el-tag size="small" effect="light">
              {{ record.type === 'wrong_question' ? '错题记录' : '掌握度记录' }}
            </el-tag>
            <span>{{ record.title }}</span>
            <span class="practice-reference__time">{{ formatTime(record.created_at) }}</span>
          </div>
        </div>
        <div v-else class="practice-recommendation__empty">课程基础推荐，无关联学习记录。</div>
      </div>
      <div v-if="practiceItems.length">
        <div v-for="(item, i) in practiceItems" :key="i" class="practice-item">
          <div class="practice-item__q">{{ i + 1 }}. {{ item.question }}</div>
          <div class="practice-item__meta">
            <el-tag size="small" effect="light">{{ item.kp_name || '综合' }}</el-tag>
            <span v-if="item.hint" class="practice-item__hint">提示：{{ item.hint }}</span>
            <el-button
              link
              type="primary"
              :disabled="item.added"
              @click="addToWrong(item)"
            >
              {{ item.added ? '已加入错题本' : '加入错题本' }}
            </el-button>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">正在根据课程知识点生成，请稍候…</div>
      <template #footer>
        <el-button :loading="generating" @click="generate">重新生成</el-button>
        <el-button type="primary" @click="practiceVisible = false">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { studentApi } from '../../api/student'
import { courseApi } from '../../api/course'
import { renderMarkdown } from '../../utils/markdown'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const courses = ref([])
const courseId = ref(null)
const kpMap = ref({})
const records = ref([])
const loading = ref(false)
const error = ref(false)
const dialogVisible = ref(false)
const current = ref(null)
const generating = ref(false)
const practiceVisible = ref(false)
const practiceItems = ref([])
const practiceRecommendation = ref(null)

// 窄屏取消操作列固定，让表格整体横向滚动，避免固定列挤压内容
const isNarrow = ref(false)
const narrowQuery = window.matchMedia('(max-width: 900px)')
function syncNarrow(e) { isNarrow.value = e.matches }

const kpCount = computed(() => new Set(records.value.map((r) => r.kp_id).filter((id) => id != null)).size)
const unclassified = computed(() => records.value.filter((r) => r.kp_id == null).length)

onMounted(async () => {
  isNarrow.value = narrowQuery.matches
  narrowQuery.addEventListener('change', syncNarrow)
  try {
    const data = await courseApi.list()
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) {
      courseId.value = courses.value[0].id
      await onCourseChange()
    }
  } catch { /* ignore */ }
})

onBeforeUnmount(() => narrowQuery.removeEventListener('change', syncNarrow))

async function onCourseChange() {
  kpMap.value = {}
  records.value = []
  if (!courseId.value) return
  try {
    const kps = await courseApi.knowledgePoints(courseId.value)
    const list = Array.isArray(kps) ? kps : []
    const m = {}
    list.forEach(k => { m[k.id] = k.name })
    kpMap.value = m
  } catch { /* ignore */ }
  await load()
}

async function load() {
  if (!courseId.value) return
  loading.value = true
  error.value = false
  try {
    records.value = await studentApi.wrongQuestions(courseId.value)
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function expand(row) {
  current.value = row
  dialogVisible.value = true
}

function kpName(id) {
  if (id === null || id === undefined) return '未归类'
  return kpMap.value[id] || '未归类'
}

function errorTypeColor(t) {
  const map = { 概念不清: 'danger', 逻辑错误: 'warning', 粗心大意: 'info', 方法不当: 'primary' }
  return map[t] || 'info'
}

function formatTime(t) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}
async function generate() {
  if (!courseId.value) return
  generating.value = true
  practiceVisible.value = true
  practiceItems.value = []
  practiceRecommendation.value = null
  try {
    const data = await studentApi.generatePractice(courseId.value, 3)
    practiceItems.value = (data.items || []).map((it) => ({ ...it, added: false }))
    practiceRecommendation.value = data.recommendation || { reason: '课程基础推荐', record_refs: [] }
  } catch {
    practiceVisible.value = false
  } finally {
    generating.value = false
  }
}

async function addToWrong(item) {
  try {
    await studentApi.createWrongQuestion({
      course_id: courseId.value,
      question_content: item.question,
      kp_name: item.kp_name,
      error_type: '练习生成',
    })
    item.added = true
    ElMessage.success('已加入错题本')
    await load()
  } catch { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.practice-recommendation {
  padding: var(--sp-3);
  margin-bottom: var(--sp-3);
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
}
.practice-recommendation__reason {
  margin: 0 0 var(--sp-2);
  color: var(--text-primary);
  font-size: var(--fs-sm);
  line-height: 1.6;
}
.practice-recommendation__empty,
.practice-reference__time {
  color: var(--text-secondary);
  font-size: var(--fs-xs);
}
.practice-reference {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
}
.practice-reference__time { margin-left: auto; }

.practice-item {
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--border);
}
.practice-item:last-child { border-bottom: none; }
.practice-item__q {
  font-size: var(--fs-sm);
  color: var(--text-primary);
  line-height: 1.7;
  margin-bottom: var(--sp-2);
}
.practice-item__meta {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.practice-item__hint {
  flex: 1;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.kpi__value--muted { color: var(--text-secondary); }

.panel__meta { font-size: var(--fs-xs); color: var(--text-placeholder); }

.wrong-table :deep(.el-table__inner-wrapper::before) { display: none; }

.question-text {
  cursor: pointer;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.question-text:hover { color: var(--color-primary); }

.dialog-section { margin-bottom: var(--sp-4); }
.dialog-label {
  font-weight: 600;
  margin-bottom: var(--sp-2);
  color: var(--text-secondary);
  font-size: var(--fs-sm);
}
.dialog-body {
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
  padding: var(--sp-3);
}
</style>
