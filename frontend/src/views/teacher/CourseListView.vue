<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">我的课程</h2>
        <p class="page-sub">创建并维护课程，进入课程管理可配置知识点与教材资料</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="importVisible = true">
          <el-icon><Download /></el-icon> 输入分享码复制
        </el-button>
        <el-button type="primary" @click="dialogVisible = true">
          <el-icon><Plus /></el-icon> 新建课程
        </el-button>
      </div>
    </div>

    <div v-if="courses.length" class="course-grid">
      <article v-for="c in courses" :key="c.id" class="course" @click="goDetail(c.id)">
        <div class="course__head">
          <span class="course__seal"><el-icon><Notebook /></el-icon></span>
          <span class="course__title">{{ c.name }}</span>
        </div>
        <p class="course__desc">{{ c.syllabus || '暂无简介' }}</p>
        <div class="course__foot">
          <el-tag size="small" effect="plain">{{ c.semester || '未设置学期' }}</el-tag>
          <span class="course__link">进入管理 →</span>
        </div>
      </article>
    </div>
    <div v-else-if="!loading" class="empty-state">还没有课程，点击右上角「新建课程」开始</div>

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

    <!-- 凭分享码复制课程 -->
    <el-dialog v-model="importVisible" title="输入分享码复制课程" width="440px">
      <el-form label-position="top">
        <el-form-item label="分享码">
          <el-input v-model="importCode" placeholder="请输入其他教师提供的 8 位分享码" maxlength="16" />
        </el-form-item>
      </el-form>
      <p class="import-hint">复制为课程快照副本，只包含课程信息、知识点与资料元数据，不包含原课程的学生与成绩数据。</p>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="doImport">复制课程</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { courseApi } from '../../api/course'
import { teacherApi } from '../../api/teacher'

const router = useRouter()
const courses = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const creating = ref(false)
const formRef = ref()

const importVisible = ref(false)
const importCode = ref('')
const importing = ref(false)

const form = reactive({ name: '', code: '', semester: '', syllabus: '' })
const rules = {
  name: [{ required: true, message: '请输入课程名', trigger: 'blur' }],
  code: [{ required: true, message: '请输入课程代码', trigger: 'blur' }],
}

onMounted(load)

async function load() {
  loading.value = true
  try {
    // 后端 /course/list 与 /teacher/courses 均直接返回数组
    const data = await teacherApi.courses()
    courses.value = Array.isArray(data) ? data : []
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

function goDetail(id) {
  router.push(`/teacher/course/${id}`)
}

async function create() {
  await formRef.value.validate()
  creating.value = true
  try {
    await courseApi.create(form)
    ElMessage.success('课程创建成功')
    dialogVisible.value = false
    Object.assign(form, { name: '', code: '', semester: '', syllabus: '' })
    load()
  } catch { /* 拦截器已提示 */ } finally {
    creating.value = false
  }
}

async function doImport() {
  const code = importCode.value.trim()
  if (!code) return ElMessage.warning('请输入分享码')
  importing.value = true
  try {
    const res = await teacherApi.importCourse(code)
    ElMessage.success(`已复制课程《${res.name}》，包含 ${res.knowledge_points} 个知识点`)
    importVisible.value = false
    importCode.value = ''
    load()
  } catch { /* 拦截器已提示 */ } finally {
    importing.value = false
  }
}
</script>

<style scoped>
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
.course__link { font-size: var(--fs-sm); color: var(--color-primary); }
.import-hint { margin-top: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
