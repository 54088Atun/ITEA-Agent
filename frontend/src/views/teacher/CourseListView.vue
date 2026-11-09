<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">我的课程</h2>
        <p class="page-sub">创建并维护课程，进入课程管理可配置知识点与教材资料</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="openTemplatePicker">
          <el-icon><CopyDocument /></el-icon> 从模板复制
        </el-button>
        <el-button @click="importVisible = true">
          <el-icon><Download /></el-icon> 输入课程码复制
        </el-button>
        <el-button type="primary" @click="dialogVisible = true">
          <el-icon><Plus /></el-icon> 新建课程
        </el-button>
      </div>
    </div>

    <div class="course-filters">
      <el-select v-model="filters.lifecycle" style="width: 140px" @change="load">
        <el-option label="正常课程" value="active" />
        <el-option label="已归档" value="archived" />
        <el-option label="回收站" value="deleted" />
      </el-select>
      <DebouncedInput
        v-model="filters.keyword"
        placeholder="搜索课程名 / 课程代码"
        clearable
        style="width: 240px"
        @keyup.enter="load"
        @debounce="load"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </DebouncedInput>
      <el-select
        v-model="filters.semester" placeholder="全部学期" clearable
        style="width: 160px" @change="load"
      >
        <el-option v-for="s in semesters" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select
        v-model="filters.audit_status" placeholder="全部审核状态" clearable
        style="width: 160px" @change="load"
      >
        <el-option label="已通过" value="approved" />
        <el-option label="审核中" value="pending" />
        <el-option label="已驳回" value="rejected" />
      </el-select>
      <span class="course-filters__count">共 {{ courses.length }} 门</span>
      <el-button v-if="hasFilters" text @click="clearFilters">清除筛选</el-button>
    </div>

    <div v-if="loading && !courses.length" class="course-grid">
      <SkeletonCard v-for="n in 4" :key="n" :rows="3" />
    </div>
    <div v-else-if="error" class="panel">
      <StateBlock state="error" @retry="load" />
    </div>
    <div v-else-if="courses.length" class="course-grid">
      <article
        v-for="c in courses" :key="c.id" class="course"
        @click="filters.lifecycle !== 'deleted' && goDetail(c.id)"
      >
        <div class="course__head">
          <span class="course__seal"><el-icon><Notebook /></el-icon></span>
          <span class="course__title">{{ c.name }}</span>
        </div>
        <p class="course__desc">{{ c.syllabus || '暂无简介' }}</p>
        <div class="course__foot">
          <span class="course__tags">
            <el-tag size="small" effect="plain">{{ c.semester || '未设置学期' }}</el-tag>
            <el-tag v-if="c.audit_status === 'pending'" size="small" type="warning" effect="plain">
              审核中
            </el-tag>
            <el-tag v-else-if="c.audit_status === 'rejected'" size="small" type="danger" effect="plain">
              已驳回 · 学生不可见
            </el-tag>
          </span>
          <span class="course__actions">
            <el-button
              v-if="filters.lifecycle !== 'deleted'"
              link type="primary" size="small" @click.stop="openDuplicate(c)"
            >复制</el-button>
            <el-button
              v-if="filters.lifecycle === 'active'"
              link type="warning" size="small" @click.stop="archiveCourse(c)"
            >归档</el-button>
            <el-button
              v-else
              link type="primary" size="small" @click.stop="restoreCourse(c)"
            >恢复</el-button>
            <el-button
              v-if="filters.lifecycle !== 'deleted'"
              link type="danger" size="small" @click.stop="removeCourse(c)"
            >删除</el-button>
            <span v-if="filters.lifecycle !== 'deleted'" class="course__link">进入管理 →</span>
          </span>
        </div>
      </article>
    </div>
    <div v-else-if="!loading && hasFilters" class="panel">
      <div class="empty-state">
        <span>没有符合条件的课程</span>
        <el-button @click="clearFilters">清除筛选</el-button>
      </div>
    </div>
    <div v-else-if="!loading" class="onboarding">
      <span class="onboarding__eyebrow">开始使用 ITEA</span>
      <h3 class="onboarding__title">先创建你的第一门课程</h3>
      <p class="onboarding__desc">
        课程是知识点、资料、班级与作业的载体。创建课程后，按下面四步即可开课；课程需平台审核通过后学生才可见。
      </p>
      <ol class="onboarding__steps">
        <li>
          <strong>1 · 建课程</strong>
          <span>填写课程名、代码与学期</span>
        </li>
        <li>
          <strong>2 · 配资料</strong>
          <span>上传大纲/课件，生成知识点草稿并采纳</span>
        </li>
        <li>
          <strong>3 · 建班级</strong>
          <span>生成邀请码，学生凭码加入</span>
        </li>
        <li>
          <strong>4 · 发任务</strong>
          <span>发布作业、考试与面试实训</span>
        </li>
      </ol>
      <div class="onboarding__actions">
        <el-button type="primary" size="large" @click="dialogVisible = true">
          创建第一门课程
        </el-button>
        <el-button size="large" @click="openTemplatePicker">从模板复制</el-button>
        <el-button size="large" @click="importVisible = true">我有课程码</el-button>
      </div>
      <p class="onboarding__hint">创建后可在「课程管理」继续补充知识点与教材资料；也可用同事的课程码复制一门课程作为起点。</p>
    </div>

    <!-- 新建课程 -->
    <el-dialog v-model="dialogVisible" title="新建课程" width="480px">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="课程名" prop="name">
          <el-input v-model="form.name" placeholder="如：数据结构" />
        </el-form-item>
        <el-form-item label="课程代码" prop="code">
          <el-input v-model="form.code" placeholder="如：CS201" />
        </el-form-item>
        <el-form-item label="学期" prop="semester">
          <el-input v-model="form.semester" placeholder="如：2026秋季" />
        </el-form-item>
        <el-form-item label="简介">
          <el-input v-model="form.syllabus" type="textarea" :rows="3" placeholder="课程简介／教学大纲（选填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <!-- 凭课程码复制课程 -->
    <el-dialog v-model="importVisible" title="输入课程码复制课程" width="440px">
      <el-form label-position="top">
        <el-form-item label="课程码">
          <el-input v-model="importCode" placeholder="教师课程码，或班级课程码" maxlength="16" />
        </el-form-item>
      </el-form>
      <p class="import-hint">教师课程码复制原课程；班级课程码复制该班绑定课程。副本只包含课程信息、知识点与资料元数据，不包含学生与成绩数据。</p>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="doImport">复制课程</el-button>
      </template>
    </el-dialog>

    <!-- 从自身历史课程复制 -->
    <el-dialog v-model="duplicateVisible" title="复制课程结构" width="480px">
      <el-form label-position="top">
        <el-form-item label="新课程名">
          <el-input v-model="duplicateForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="课程代码">
          <el-input v-model="duplicateForm.code" maxlength="20" placeholder="留空自动生成（如 CS201-C1）" />
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="duplicateForm.semester" maxlength="20" placeholder="留空沿用源课程学期" />
        </el-form-item>
      </el-form>
      <p class="duplicate-hint">
        只复制课程信息、知识点树与资料元数据，不含选课关系、学情、班级、作业与考试。
      </p>
      <template #footer>
        <el-button @click="duplicateVisible = false">取消</el-button>
        <el-button type="primary" :loading="duplicating" @click="confirmDuplicate">复制</el-button>
      </template>
    </el-dialog>

    <!-- 选择模板课程 -->
    <el-dialog v-model="templateVisible" title="从模板复制课程" width="560px">
      <div v-loading="templateLoading" class="template-list">
        <div v-for="t in templates" :key="t.id" class="template-item">
          <div class="template-item__main">
            <strong class="template-item__name">{{ t.name }}</strong>
            <span class="template-item__meta">
              {{ t.code }} · {{ t.semester || '未设置学期' }} ·
              {{ t.knowledge_points }} 个知识点 · {{ t.materials }} 份资料
            </span>
          </div>
          <el-button type="primary" plain size="small" @click="useTemplate(t)">使用</el-button>
        </div>
        <div v-if="!templateLoading && !templates.length" class="empty-state">
          暂无历史课程可作为模板，可先用课程码复制一门课程。
        </div>
      </div>
      <template #footer>
        <el-button @click="templateVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { courseApi } from '../../api/course'
import { teacherApi } from '../../api/teacher'
import { codeApi } from '../../api/codes'
import SkeletonCard from '../../components/SkeletonCard.vue'
import StateBlock from '../../components/StateBlock.vue'
import DebouncedInput from '../../components/DebouncedInput.vue'

const router = useRouter()
const courses = ref([])
const loading = ref(false)
const error = ref(false)
const dialogVisible = ref(false)
const creating = ref(false)
const formRef = ref()

const filters = reactive({ keyword: '', semester: '', audit_status: '', lifecycle: 'active' })
const semesters = ref([])
const hasFilters = computed(
  () => Boolean(
    filters.keyword.trim() || filters.semester || filters.audit_status
    || filters.lifecycle !== 'active',
  ),
)

const importVisible = ref(false)
const importCode = ref('')
const importing = ref(false)

const duplicateVisible = ref(false)
const duplicating = ref(false)
const duplicateSource = ref(null)
const duplicateForm = reactive({ name: '', code: '', semester: '' })

const templateVisible = ref(false)
const templateLoading = ref(false)
const templates = ref([])

const form = reactive({ name: '', code: '', semester: '', syllabus: '' })
const rules = {
  name: [{ required: true, message: '请输入课程名', trigger: 'blur' }],
  code: [{ required: true, message: '请输入课程代码', trigger: 'blur' }],
}

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const params = { lifecycle: filters.lifecycle }
    if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
    if (filters.semester) params.semester = filters.semester
    if (filters.audit_status) params.audit_status = filters.audit_status
    // 后端 /course/list 与 /teacher/courses 均直接返回数组
    const data = await teacherApi.courses(params)
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) {
      const seen = new Set(semesters.value)
      courses.value.forEach((c) => { if (c.semester) seen.add(c.semester) })
      semesters.value = [...seen].sort()
    }
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.semester = ''
  filters.audit_status = ''
  filters.lifecycle = 'active'
}

function clearFilters() {
  resetFilters()
  load()
}

async function archiveCourse(course) {
  try {
    await ElMessageBox.confirm(
      `归档后《${course.name}》学生暂不可见，可随时恢复。确认归档？`,
      '归档课程',
      { type: 'warning', confirmButtonText: '归档', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await teacherApi.archiveCourse(course.id)
    ElMessage.success(`已归档课程《${course.name}》`)
    load()
  } catch { /* 拦截器已提示 */ }
}

async function restoreCourse(course) {
  try {
    await ElMessageBox.confirm(
      `恢复后《${course.name}》将回到正常课程列表。确认恢复？`,
      '恢复课程',
      { type: 'warning', confirmButtonText: '恢复', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await teacherApi.restoreCourse(course.id)
    ElMessage.success(`已恢复课程《${course.name}》`)
    load()
  } catch { /* 拦截器已提示 */ }
}

async function removeCourse(course) {
  try {
    await ElMessageBox.confirm(
      `课程《${course.name}》将移入回收站，选课、学情、素材和作业等关联数据会保留。确认删除？`,
      '移入回收站',
      { type: 'warning', confirmButtonText: '移入回收站', cancelButtonText: '取消' },
    )
  } catch { return }
  try {
    await teacherApi.deleteCourse(course.id)
    ElMessage.success('课程已移入回收站')
    load()
  } catch { /* 拦截器已提示 */ }
}

function goDetail(id) {
  router.push(`/teacher/course/${id}`)
}

async function create() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  creating.value = true
  try {
    await courseApi.create(form)
    ElMessage.success('课程已创建，待平台审核通过后学生可见')
    dialogVisible.value = false
    Object.assign(form, { name: '', code: '', semester: '', syllabus: '' })
    resetFilters()
    load()
  } catch { /* 拦截器已提示 */ } finally {
    creating.value = false
  }
}

async function doImport() {
  const code = importCode.value.trim()
  if (!code) return ElMessage.warning('请输入课程码')
  importing.value = true
  try {
    const res = await codeApi.redeem(code)
    ElMessage.success(`已复制课程《${res.name}》，包含 ${res.knowledge_points} 个知识点`)
    importVisible.value = false
    importCode.value = ''
    resetFilters()
    load()
  } catch { /* 拦截器已提示 */ } finally {
    importing.value = false
  }
}

function openDuplicate(course) {
  duplicateSource.value = course
  Object.assign(duplicateForm, {
    name: `${course.name}（副本）`.slice(0, 100),
    code: '',
    semester: course.semester || '',
  })
  duplicateVisible.value = true
}

async function openTemplatePicker() {
  templateVisible.value = true
  templateLoading.value = true
  try {
    const res = await teacherApi.courseTemplates()
    templates.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    templates.value = []
  } finally {
    templateLoading.value = false
  }
}

function useTemplate(template) {
  templateVisible.value = false
  openDuplicate(template)
}

async function confirmDuplicate() {
  if (!duplicateSource.value) return
  duplicating.value = true
  try {
    const res = await teacherApi.duplicateCourse(duplicateSource.value.id, {
      name: duplicateForm.name.trim() || undefined,
      code: duplicateForm.code.trim() || undefined,
      semester: duplicateForm.semester.trim() || undefined,
    })
    ElMessage.success(
      res.audit_status === 'approved'
        ? `已复制课程《${res.name}》`
        : `已复制课程《${res.name}》，待平台审核`,
    )
    duplicateVisible.value = false
    resetFilters()
    load()
  } catch { /* 拦截器已提示 */ } finally {
    duplicating.value = false
  }
}
</script>

<style scoped>
.course-filters {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-bottom: var(--sp-4);
}
.course-filters__count { font-size: var(--fs-xs); color: var(--text-secondary); }
.course-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: var(--sp-4); }
.course {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition: box-shadow var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.course:hover { box-shadow: var(--shadow-sm); border-color: var(--brand-300); }
.course__head { display: flex; align-items: center; gap: var(--sp-3); }
.course__seal {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; flex-shrink: 0;
  border: 1px solid var(--brand-300); border-radius: var(--r-sm);
  color: var(--color-primary); background: var(--color-primary-wash);
}
.course__title { font-family: var(--font-serif); font-size: var(--fs-md); font-weight: 600; color: var(--text-primary); }
.course__desc { flex: 1; min-height: 42px; margin: 0; font-size: var(--fs-sm); line-height: var(--lh-base); color: var(--text-secondary); }
.course__foot { display: flex; align-items: center; justify-content: space-between; padding-top: var(--sp-3); border-top: 1px dashed var(--border); }
.course__tags { display: inline-flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.course__actions { display: inline-flex; align-items: center; justify-content: flex-end; gap: var(--sp-2); flex-wrap: wrap; }
.course__link { font-size: var(--fs-sm); color: var(--color-primary); }
.import-hint { margin-top: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
.duplicate-hint { margin-top: var(--sp-2); font-size: var(--fs-xs); line-height: var(--lh-base); color: var(--text-secondary); }
.template-list { display: flex; flex-direction: column; gap: var(--sp-2); min-height: 80px; }
.template-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
}
.template-item__main { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.template-item__name { font-size: var(--fs-sm); color: var(--text-primary); }
.template-item__meta { font-size: var(--fs-xs); color: var(--text-secondary); }
.onboarding {
  max-width: 760px;
  padding: var(--sp-6);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-xs);
}
.onboarding__eyebrow {
  font-size: var(--fs-xs);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-primary);
}
.onboarding__title {
  margin: var(--sp-2) 0 var(--sp-2);
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  color: var(--text-primary);
}
.onboarding__desc {
  margin: 0 0 var(--sp-5);
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  color: var(--text-secondary);
}
.onboarding__steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--sp-3);
  margin: 0 0 var(--sp-5);
  padding: 0;
  list-style: none;
}
.onboarding__steps li {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-3);
  background: var(--bg-subtle, var(--bg-card));
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
}
.onboarding__steps strong {
  font-size: var(--fs-sm);
  color: var(--text-primary);
}
.onboarding__steps span {
  font-size: var(--fs-xs);
  line-height: var(--lh-base);
  color: var(--text-secondary);
}
.onboarding__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}
.onboarding__hint {
  margin: var(--sp-4) 0 0;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

@media (max-width: 767px) {
  /* 课程卡在大纲很长时先收成三行，避免一屏只看到一门课 */
  .course__desc {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  /* 筛选控件占满整行，避免 140/160/240px 的固定宽度在窄屏参差不齐 */
  .course-filters {
    gap: var(--sp-2);
  }
  .course-filters :deep(.el-input) {
    width: 100% !important;
  }
  /* 生命周期独占一行；学期与审核状态并排，减少一屏筛选占用 */
  .course-filters :deep(.el-select) {
    width: calc(50% - var(--sp-1)) !important;
  }
  .course-filters :deep(.el-select:first-child) {
    width: 100% !important;
  }
  .course-filters__count {
    width: 100%;
  }
  .page-head__actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-2);
  }
  .page-head__actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }
  .page-head__actions :deep(.el-button--primary) {
    grid-column: 1 / -1;
  }
}
</style>
