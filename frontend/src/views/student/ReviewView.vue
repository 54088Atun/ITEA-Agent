<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">复习计划</h2>
        <p class="page-sub">按遗忘曲线为每道错题安排 6 轮复习，完成后自动推下一轮</p>
      </div>
      <div class="page-head__actions">
        <el-select v-model="courseId" placeholder="选择课程" filterable style="width: 220px" @change="load">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-radio-group v-model="statusFilter" @change="load" :disabled="!courseId">
          <el-radio-button value="pending">待复习</el-radio-button>
          <el-radio-button value="done">已完成</el-radio-button>
          <el-radio-button value="all">全部</el-radio-button>
        </el-radio-group>
        <el-button @click="load" :disabled="!courseId">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <div v-if="!courseId" class="panel">
      <div class="empty-state">请先在右上角选择一门课程</div>
    </div>

    <div v-else class="plan-wrap">
      <div v-if="error" class="panel">
        <StateBlock state="error" @retry="load" />
      </div>

      <div v-else-if="loading && !plans.length" class="plan-grid">
        <SkeletonCard v-for="n in 4" :key="n" :rows="3" />
      </div>

      <div v-else-if="!plans.length" class="panel">
        <StateBlock
          state="empty"
          :title="statusFilter === 'done' ? '还没有已完成的复习计划' : '暂无复习计划'"
          hint="做错题目后会自动排程"
        />
      </div>

      <div v-else class="plan-grid">
        <article v-for="p in plans" :key="p.id" :class="['plan', { 'plan--done': p.status === 'done' }]">
          <header class="plan__head">
            <div class="plan__title">
              错题 #{{ p.wrong_question_id }}
              <span class="plan__sub">复习计划</span>
            </div>
            <el-tag :type="p.status === 'done' ? 'success' : 'warning'" size="small" effect="light">
              {{ p.status === 'done' ? '已完成' : '待复习' }}
            </el-tag>
          </header>

          <div class="plan__meta">
            <span class="plan__meta-item">
              <el-icon><Clock /></el-icon>
              下次复习 {{ formatTime(p.next_review_at) }}
            </span>
            <span class="plan__meta-item">
              <el-icon><DataLine /></el-icon>
              已复习 {{ p.review_count }} 轮 · 间隔 {{ p.interval_days }} 天
            </span>
          </div>

          <div class="plan__progress">
            <el-progress
              :percentage="Math.min((p.review_count / 6) * 100, 100)"
              :status="p.status === 'done' ? 'success' : ''"
              :stroke-width="8"
            />
            <span class="plan__round">第 {{ p.review_count || 0 }} / 6 轮</span>
          </div>

          <footer class="plan__foot">
            <span class="plan__hint">遗忘曲线 6 轮复习</span>
            <el-button v-if="p.status !== 'done'" type="success" size="small" @click="complete(p)">
              <el-icon><Check /></el-icon> 标记已复习
            </el-button>
          </footer>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { studentApi } from '../../api/student'
import { courseApi } from '../../api/course'
import SkeletonCard from '../../components/SkeletonCard.vue'
import StateBlock from '../../components/StateBlock.vue'

const courses = ref([])
const courseId = ref(null)
const plans = ref([])
const statusFilter = ref('pending')
const loading = ref(false)
const error = ref(false)

onMounted(async () => {
  try {
    const data = await courseApi.list()
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) {
      courseId.value = courses.value[0].id
      await load()
    }
  } catch { /* ignore */ }
})

async function load() {
  if (!courseId.value) return
  loading.value = true
  error.value = false
  try {
    plans.value = await studentApi.reviewPlans(courseId.value, statusFilter.value)
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

async function complete(plan) {
  try {
    const res = await studentApi.completeReviewPlan(plan.id)
    if (res.status === 'done') {
      ElMessage.success('恭喜!该错题已完成全部复习轮次')
    } else {
      ElMessage.success(`已记录!下一轮复习时间:${formatTime(res.next_review_at)}`)
    }
    await load()
  } catch { /* 拦截器已提示 */ }
}

function formatTime(t) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.plan-wrap { min-height: 200px; }

.plan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: var(--sp-4);
}

.plan {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-xs);
  transition: box-shadow var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.plan:hover { box-shadow: var(--shadow-sm); }
.plan--done { opacity: 0.72; }

.plan__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}
.plan__title {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
}
.plan__sub {
  font-family: var(--font-sans);
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--text-secondary);
  margin-left: var(--sp-2);
}

.plan__meta {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.plan__meta-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.plan__progress {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.plan__progress :deep(.el-progress) { flex: 1; }
.plan__round {
  flex-shrink: 0;
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.plan__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--border);
}
.plan__hint { font-size: var(--fs-xs); color: var(--text-placeholder); }

/* 窄屏单列，避免 360px 最小列宽撑出横向滚动 */
@media (max-width: 480px) {
  .plan-grid { grid-template-columns: 1fr; }
}

</style>
