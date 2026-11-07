<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">我的学情</h2>
        <p class="page-sub">掌握度由练习记录与对话复盘累计得出，低于 60 分列为薄弱知识点</p>
      </div>
      <div class="page-head__actions">
        <el-select
          v-model="courseId" placeholder="选择课程" filterable clearable
          style="width: 240px" @change="onCourseChange"
        >
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id">
            <span>{{ c.name }}</span>
            <el-tag v-if="joinedIds.includes(c.id)" size="small" type="success" style="margin-left: 8px">已加入</el-tag>
          </el-option>
        </el-select>
        <el-button :disabled="!courseId || !joined" @click="refresh">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <div v-if="!courseId" class="panel">
      <div class="empty-state">请先在右上角选择一门课程</div>
    </div>

    <div v-else class="page__body">
      <div v-if="loading && !progress" class="panel">
        <div class="kpi-skeleton">
          <SkeletonCard v-for="n in 4" :key="n" :rows="2" />
        </div>
      </div>

      <!-- 未加入课程 -->
      <div v-else-if="!joined" class="panel">
        <div class="empty-state">
          <span>你还没有加入该课程</span>
          <el-button type="primary" @click="router.push('/student/tutor')">
            <el-icon><Plus /></el-icon> 去课程助教加入班级
          </el-button>
        </div>
      </div>

      <template v-else>
        <div v-if="!progress" class="panel">
          <div class="empty-state">暂无学情数据，去课程助教聊几句吧</div>
        </div>

        <template v-if="progress">
          <!-- 概览：统一 KPI 卡组 -->
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">总体学习进度</div>
              <div class="kpi__value">
                <CountUp :value="Math.round(progress.overall_progress || 0)" /><span class="kpi__unit">分</span>
              </div>
              <div class="kpi__hint">课程整体完成度</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">已跟踪知识点</div>
              <div class="kpi__value">
                <CountUp :value="masteryList.length" /><span class="kpi__unit">个</span>
              </div>
              <div class="kpi__hint">已产生练习或对话记录</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">掌握良好</div>
              <div class="kpi__value kpi__value--good">
                <CountUp :value="goodPoints.length" /><span class="kpi__unit">个</span>
              </div>
              <div class="kpi__hint">掌握度 ≥ 80 分</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">薄弱知识点</div>
              <div class="kpi__value kpi__value--weak">
                <CountUp :value="weakPoints.length" /><span class="kpi__unit">个</span>
              </div>
              <div class="kpi__hint">掌握度 &lt; 60 分，建议优先补强</div>
            </div>
          </div>

          <!-- 掌握度分布 + 明细 -->
          <div class="panel">
            <div class="panel__head">
              <span class="panel__title">知识点掌握度</span>
              <div class="legend">
                <span class="legend__item"><i class="dot dot--good"></i>良好 {{ goodPoints.length }}</span>
                <span class="legend__item"><i class="dot dot--mid"></i>基本 {{ midPoints.length }}</span>
                <span class="legend__item"><i class="dot dot--weak"></i>薄弱 {{ weakPoints.length }}</span>
              </div>
            </div>

            <div class="panel__body">
              <!-- 分布条：一眼看清结构，比单个进度环信息量大 -->
              <div v-if="masteryList.length" class="dist">
                <span
                  v-for="seg in distSegments"
                  :key="seg.key"
                  :class="['dist__seg', `dist__seg--${seg.key}`]"
                  :style="{ width: seg.width + '%' }"
                  :title="`${seg.label} ${seg.count} 个`"
                ></span>
              </div>

              <div v-for="m in masteryList" :key="m.kp_id" class="mastery-item">
                <div class="mastery-name" :title="m.kp_name">{{ m.kp_name }}</div>
                <el-progress
                  :percentage="m.mastery_level"
                  :stroke-width="10"
                  :class="['mastery-bar', `mastery-bar--${levelKey(m.mastery_level)}`]"
                />
                <span class="mastery-score">{{ m.mastery_level }}</span>
                <el-tag :type="levelTag(m.mastery_level)" size="small" effect="light">{{ levelLabel(m.mastery_level) }}</el-tag>
                <el-button size="small" plain type="primary" @click="openPractice(m)">提交练习</el-button>
              </div>

              <div v-if="!masteryList.length" class="empty-state">暂无掌握度记录</div>

              <div v-if="weakPoints.length" class="panel__foot">
                <span class="panel__foot-text">薄弱知识点已按遗忘曲线排入复习计划，也可直接做一轮面试实训。</span>
                <el-button size="small" plain @click="goInterview">去面试实训补强</el-button>
              </div>
            </div>
          </div>
        </template>
      </template>
    </div>

    <!-- 提交练习 -->
    <el-dialog v-model="practiceVisible" title="提交练习" width="520px">
      <el-form label-width="90px">
        <el-form-item label="知识点">
          <el-tag>{{ practiceForm.kp_name || '未指定' }}</el-tag>
        </el-form-item>
        <el-form-item label="练习类型">
          <el-radio-group v-model="practiceForm.type">
            <el-radio-button value="in_class">课堂练习</el-radio-button>
            <el-radio-button value="variant">变式题</el-radio-button>
            <el-radio-button value="code">代码题</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="练习内容">
          <el-input v-model="practiceForm.content" type="textarea" :rows="4" placeholder="粘贴题目或你的作答内容" />
        </el-form-item>
        <el-form-item label="自评结果">
          <el-radio-group v-model="practiceForm.is_correct">
            <el-radio :value="true">正确</el-radio>
            <el-radio :value="false">错误</el-radio>
            <el-radio :value="null">暂不评价</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="practiceVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitPractice">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { studentApi } from '../../api/student'
import { courseApi } from '../../api/course'
import SkeletonCard from '../../components/SkeletonCard.vue'
import CountUp from '../../components/CountUp.vue'

const router = useRouter()
const courses = ref([])
const joinedIds = ref([])
const courseId = ref(null)
const progress = ref(null)
const loading = ref(false)

const practiceVisible = ref(false)
const submitting = ref(false)
const practiceForm = reactive({ kp_id: null, kp_name: '', type: 'in_class', content: '', is_correct: null })

const joined = computed(() => joinedIds.value.includes(courseId.value))

onMounted(async () => {
  try {
    // 课程列表接口直接返回数组
    const [data, mine] = await Promise.all([
      courseApi.list(),
      studentApi.courses().catch(() => []),
    ])
    courses.value = Array.isArray(data) ? data : []
    joinedIds.value = Array.isArray(mine) ? mine.map((c) => c.id) : []
    if (courses.value.length) {
      // 优先落到「我的课程」中的第一门，其次退回课程列表第一门
      const preferred = Array.isArray(mine) && mine.length ? mine[0].id : null
      const target = courses.value.find((c) => c.id === preferred) || courses.value[0]
      courseId.value = target.id
      if (joined.value) load()
    }
  } catch { /* 拦截器已提示 */ }
})

function onCourseChange() {
  progress.value = null
  if (joined.value) load()
}

async function refresh() {
  if (!courseId.value) return
  if (!joined.value) return
  await load()
}

async function load() {
  if (!courseId.value) return
  loading.value = true
  try {
    progress.value = await studentApi.progress(courseId.value)
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

const masteryList = computed(() => progress.value?.mastery || [])
const weakPoints = computed(() => masteryList.value.filter((m) => m.mastery_level < 60))
const midPoints = computed(() => masteryList.value.filter((m) => m.mastery_level >= 60 && m.mastery_level < 80))
const goodPoints = computed(() => masteryList.value.filter((m) => m.mastery_level >= 80))

// 分布条按占比渲染
const distSegments = computed(() => {
  const total = masteryList.value.length || 1
  return [
    { key: 'good', label: '掌握良好', count: goodPoints.value.length },
    { key: 'mid', label: '基本掌握', count: midPoints.value.length },
    { key: 'weak', label: '薄弱', count: weakPoints.value.length },
  ].map((s) => ({ ...s, width: (s.count / total) * 100 }))
})

function levelKey(level) {
  if (level >= 80) return 'good'
  if (level >= 60) return 'mid'
  return 'weak'
}
function levelTag(level) {
  if (level >= 80) return 'success'
  if (level >= 60) return 'warning'
  return 'danger'
}
function levelLabel(level) {
  if (level >= 80) return '掌握良好'
  if (level >= 60) return '基本掌握'
  return '薄弱'
}
function goInterview() {
  router.push('/student/interview')
}

function openPractice(m) {
  Object.assign(practiceForm, {
    kp_id: m.kp_id,
    kp_name: m.kp_name,
    type: 'in_class',
    content: '',
    is_correct: null,
  })
  practiceVisible.value = true
}

async function submitPractice() {
  if (!practiceForm.content.trim()) return ElMessage.warning('请填写练习内容')
  submitting.value = true
  try {
    await studentApi.practice({
      course_id: courseId.value,
      kp_id: practiceForm.kp_id,
      type: practiceForm.type,
      content: practiceForm.content,
      is_correct: practiceForm.is_correct,
    })
    ElMessage.success('练习已提交')
    practiceVisible.value = false
  } catch { /* 拦截器已提示 */ } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.page__body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  flex: 1;
  min-height: 240px;
}

.kpi-skeleton {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sp-4);
}

/* KPI 数值语义色 */
.kpi__value--good { color: var(--color-success); }
.kpi__value--weak { color: var(--color-danger); }

/* 分布条 */
.dist {
  display: flex;
  height: 8px;
  border-radius: var(--r-pill);
  overflow: hidden;
  background: var(--bg-subtle);
  margin-bottom: var(--sp-5);
}
.dist__seg { height: 100%; transition: width var(--dur) var(--ease); }
.dist__seg--good { background: var(--color-success); }
.dist__seg--mid { background: var(--color-warning); }
.dist__seg--weak { background: var(--color-danger); }

.legend {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.legend__item { display: inline-flex; align-items: center; gap: var(--sp-1); }
.dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  display: inline-block;
}
.dot--good { background: var(--color-success); }
.dot--mid { background: var(--color-warning); }
.dot--weak { background: var(--color-danger); }

/* 知识点行 */
.mastery-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--border);
}
.mastery-item:last-of-type { border-bottom: 0; }
.mastery-name {
  width: 180px;
  flex-shrink: 0;
  font-size: var(--fs-base);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mastery-bar { flex: 1; }
/* 进度条颜色交给 token：el-progress 的 color 属性只吃 JS 快照值，切主题不会更新 */
.mastery-bar--good :deep(.el-progress-bar__inner) { background: var(--chart-good); }
.mastery-bar--mid :deep(.el-progress-bar__inner) { background: var(--chart-mid); }
.mastery-bar--weak :deep(.el-progress-bar__inner) { background: var(--chart-weak); }
.mastery-score {
  width: 42px;
  text-align: right;
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  color: var(--text-secondary);
}

.panel__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-top: var(--sp-4);
  padding-top: var(--sp-4);
  border-top: 1px dashed var(--border);
}
.panel__foot-text {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

@media (max-width: 720px) {
  .mastery-name { width: 110px; }
  .mastery-score { display: none; }
}
</style>
