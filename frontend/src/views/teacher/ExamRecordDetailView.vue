<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="backToExam">
          <el-icon><ArrowLeft /></el-icon> 返回试卷详情
        </el-button>
        <h2 class="page-title">{{ record?.student_name || '答卷详情' }}</h2>
        <p class="page-sub">{{ record?.exam_title || '' }} · 答卷 #{{ record?.record_id }}</p>
      </div>
      <div v-if="record" class="page-head__actions">
        <el-button :loading="aiGrading" @click="aiGrade">AI 批改简答</el-button>
        <el-button type="primary" :loading="confirming" :disabled="!hasShort" @click="confirmGrade">
          确认简答得分
        </el-button>
      </div>
    </div>

    <div v-if="loading" class="panel">
      <SkeletonTable :rows="6" :cols="4" />
    </div>
    <StateBlock v-else-if="error" state="error" title="答卷详情加载失败" @retry="load" />
    <template v-else-if="record">
      <div class="kpi-grid">
        <div class="kpi-card">
          <span>总分</span>
          <strong>{{ record.score }} / {{ record.total_score }}</strong>
        </div>
        <div class="kpi-card">
          <span>客观题</span>
          <strong>{{ record.objective_score }}</strong>
        </div>
        <div class="kpi-card">
          <span>简答题</span>
          <strong>{{ record.short_score }}</strong>
        </div>
        <div class="kpi-card">
          <span>正确题数</span>
          <strong>{{ record.correct_count }}</strong>
        </div>
        <div class="kpi-card">
          <span>待批改</span>
          <strong>{{ record.pending_manual }}</strong>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">作答概览</span>
        </div>
        <div class="meta-row">
          <el-tag size="small" effect="light">提交于 {{ formatTime(record.submitted_at) }}</el-tag>
          <el-tag v-if="record.graded_at" type="success" size="small" effect="light">已批改</el-tag>
          <el-tag v-else type="warning" size="small" effect="light">待确认</el-tag>
          <el-tag v-if="record.timed_out" type="warning" size="small" effect="light">超时提交</el-tag>
          <el-tag v-if="record.violations" type="danger" size="small" effect="light">
            切屏 {{ record.violations }} 次
          </el-tag>
          <el-tag v-if="record.copy_count" size="small" effect="light">复制 {{ record.copy_count }} 次</el-tag>
          <el-tag v-if="record.paste_count" size="small" effect="light">粘贴 {{ record.paste_count }} 次</el-tag>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">逐题作答</span>
          <span class="panel__hint">AI 只给建议，确认后才写入成绩</span>
        </div>
        <div class="question-list">
          <article v-for="(q, index) in record.questions" :key="q.id" class="question-item">
            <div class="question-item__head">
              <span class="question-item__index">{{ index + 1 }}</span>
              <el-tag :type="typeTag(q.type)" size="small" effect="light">{{ typeLabel(q.type) }}</el-tag>
              <span class="question-item__stem">{{ q.stem }}</span>
              <span class="dim">{{ q.awarded ?? '—' }} / {{ q.score }} 分</span>
            </div>

            <ul v-if="q.options && q.options.length" class="option-list">
              <li v-for="op in q.options" :key="op.key" class="option-item">
                <span class="option-key">{{ op.key }}</span>
                <span>{{ op.text }}</span>
              </li>
            </ul>

            <p class="answer-line">
              <span class="answer-line__label">学生作答</span>
              <span>{{ q.my_answer || '未作答' }}</span>
            </p>
            <p class="answer-line">
              <span class="answer-line__label">参考答案</span>
              <span>{{ answerText(q) }}</span>
            </p>

            <template v-if="q.type === 'short'">
              <div v-if="q.ai_suggestion" class="ai-tip">
                AI 建议：{{ q.ai_suggestion.score }} 分 · {{ q.ai_suggestion.feedback }}
                <el-tag type="warning" size="small" effect="light">待确认</el-tag>
              </div>
              <div class="score-row">
                得分：
                <el-input-number v-model="shortScores[q.id]" :min="0" :max="q.score" size="small" />
                <span class="dim">/ {{ q.score }} 分</span>
              </div>
            </template>
            <div v-else class="result-line" :class="{ 'result-line--wrong': !q.correct }">
              {{ q.correct ? '回答正确' : (q.type === 'multiple' && q.awarded > 0 ? '部分正确' : '回答错误') }}
              · 得 {{ q.awarded }} 分
            </div>
          </article>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { examApi } from '../../api/exams'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const route = useRoute()
const router = useRouter()
const recordId = Number(route.params.id)

const loading = ref(true)
const error = ref(false)
const record = ref(null)
const shortScores = ref({})
const aiGrading = ref(false)
const confirming = ref(false)

const TYPE_LABELS = { single: '单选', multiple: '多选', judge: '判断', short: '简答' }

const hasShort = computed(() =>
  (record.value?.questions || []).some((q) => q.type === 'short'),
)

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const data = await examApi.examRecord(recordId)
    record.value = data
    const init = {}
    for (const q of data.questions || []) {
      if (q.type === 'short') {
        init[q.id] = q.awarded != null ? q.awarded : (q.ai_suggestion?.score ?? 0)
      }
    }
    shortScores.value = init
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type
}

function typeTag(type) {
  return { single: '', multiple: 'success', judge: 'warning', short: 'info' }[type] || 'info'
}

function answerText(q) {
  if (q.type === 'judge') return String(q.answer).toLowerCase() === 'true' ? '正确' : '错误'
  return q.answer || '—'
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

function backToExam() {
  const examId = record.value?.exam_id
  if (examId) router.push(`/teacher/exams/${examId}`)
  else router.back()
}

async function aiGrade() {
  aiGrading.value = true
  try {
    await examApi.aiGradeRecord(recordId)
    ElMessage.success('AI 建议已生成，请核对后确认')
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    aiGrading.value = false
  }
}

async function confirmGrade() {
  confirming.value = true
  try {
    const res = await examApi.confirmRecord(recordId, shortScores.value)
    ElMessage.success(`已确认，当前总分 ${res.score}`)
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    confirming.value = false
  }
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}
.kpi-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-xs);
}
.kpi-card span { font-size: var(--fs-xs); color: var(--text-secondary); }
.kpi-card strong { font-size: var(--fs-xl); color: var(--text-primary); }
.panel { margin-bottom: var(--sp-4); }
.panel__hint { margin-left: auto; font-size: var(--fs-xs); color: var(--text-secondary); }
.meta-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--sp-2); }
.question-list { display: flex; flex-direction: column; gap: var(--sp-3); }
.question-item {
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-elevated);
}
.question-item__head { display: flex; align-items: baseline; gap: var(--sp-2); }
.question-item__index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-primary-wash);
  color: var(--color-primary);
  font-size: var(--fs-xs);
  font-weight: 600;
}
.question-item__stem { flex: 1; color: var(--text-primary); line-height: 1.7; white-space: pre-wrap; }
.option-list { display: flex; flex-direction: column; gap: 6px; margin: var(--sp-2) 0 0; padding: 0; list-style: none; }
.option-item { display: flex; gap: var(--sp-2); font-size: var(--fs-sm); color: var(--text-primary); }
.option-key { color: var(--text-secondary); font-weight: 600; }
.answer-line {
  display: flex;
  gap: var(--sp-2);
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-sm);
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
.answer-line__label { flex-shrink: 0; color: var(--text-secondary); font-weight: 600; }
.ai-tip {
  margin-top: var(--sp-2);
  padding: var(--sp-2);
  border-radius: var(--r-sm);
  background: var(--bg-subtle);
  font-size: var(--fs-xs);
  line-height: 1.7;
}
.score-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
}
.result-line {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--color-success, #2f7d32);
}
.result-line--wrong { color: var(--color-danger, #c0392b); }
.dim { font-size: var(--fs-xs); color: var(--text-placeholder); }
</style>
