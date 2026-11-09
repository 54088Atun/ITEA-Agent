<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">我的班级</h2>
        <p class="page-sub">查看已加入的班级，并按姓名或邮箱查找同学</p>
      </div>
      <div class="page-head__actions">
        <el-button type="primary" @click="joinVisible = true">
          <el-icon><UserFilled /></el-icon> 加入班级
        </el-button>
      </div>
    </div>

    <div v-if="loading && !classes.length" class="class-grid">
      <SkeletonCard v-for="n in 3" :key="n" :rows="3" />
    </div>
    <StateBlock v-else-if="error" state="error" title="班级加载失败" @retry="load" />
    <div v-else-if="classes.length" class="class-grid">
      <article v-for="item in classes" :key="item.id" class="class-card">
        <header class="class-card__head">
          <span class="class-card__seal"><el-icon><Notebook /></el-icon></span>
          <div class="class-card__title-wrap">
            <h3 class="class-card__title">{{ item.name }}</h3>
            <span class="class-card__sub">
              {{ item.course_name || '未绑定课程' }} · {{ item.semester || '未设置学期' }}
            </span>
          </div>
          <el-tag size="small" effect="light">
            {{ roleLabel(item.my_role) }}
          </el-tag>
        </header>

        <p class="class-card__meta">班级人数 {{ item.member_count }} / {{ item.max_students }}</p>

        <div class="search-row">
          <el-input
            v-model="keywords[item.id]"
            clearable
            placeholder="查找同学：姓名 / 邮箱"
            @keyup.enter="search(item)"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-button :loading="searching[item.id]" @click="search(item)">查找</el-button>
        </div>

        <el-table
          v-if="results[item.id]?.length"
          :data="results[item.id]"
          size="small"
          class="member-table"
        >
          <el-table-column prop="name" label="姓名" min-width="100" />
          <el-table-column label="角色" width="100">
            <template #default="{ row }">{{ roleLabel(row.role) }}</template>
          </el-table-column>
          <el-table-column label="头衔" min-width="110">
            <template #default="{ row }">{{ row.title || '—' }}</template>
          </el-table-column>
        </el-table>
        <p v-else-if="searched[item.id]" class="search-hint">未找到匹配的成员</p>
      </article>
    </div>
    <div v-else class="panel">
      <StateBlock state="empty" title="还没有加入班级" hint="向老师索取课程码后加入班级" />
    </div>

    <el-dialog v-model="joinVisible" title="使用课程码加入" width="min(420px, 92vw)">
      <el-input v-model="inviteCode" placeholder="输入教师提供的课程码" @keyup.enter="join" />
      <p class="join-hint">学生使用班级课程码加入班级；教师课程码仅教师可用。</p>
      <template #footer>
        <el-button @click="joinVisible = false">取消</el-button>
        <el-button type="primary" :loading="joining" @click="join">加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { classroomApi } from '../../api/classroom'
import { codeApi } from '../../api/codes'
import SkeletonCard from '../../components/SkeletonCard.vue'
import StateBlock from '../../components/StateBlock.vue'

const ROLE_LABELS = {
  head_teacher: '班主任',
  teacher: '任课教师',
  monitor: '班长',
  representative: '课代表',
  student: '普通学生',
  custom: '自定义',
}

const loading = ref(true)
const error = ref(false)
const classes = ref([])
const keywords = reactive({})
const results = reactive({})
const searching = reactive({})
const searched = reactive({})

const joinVisible = ref(false)
const joining = ref(false)
const inviteCode = ref('')

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const data = await classroomApi.mine()
    classes.value = Array.isArray(data) ? data : []
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function roleLabel(role) {
  return ROLE_LABELS[role] || role || '—'
}

async function search(item) {
  searching[item.id] = true
  try {
    const data = await classroomApi.searchMembers(item.id, (keywords[item.id] || '').trim())
    results[item.id] = data.items || []
    searched[item.id] = true
  } catch { /* 拦截器已提示 */ } finally {
    searching[item.id] = false
  }
}

async function join() {
  const code = inviteCode.value.trim()
  if (!code) return ElMessage.warning('请输入课程码')
  joining.value = true
  try {
    const data = await codeApi.redeem(code)
    ElMessage.success(`已加入班级：${data.class_name}`)
    joinVisible.value = false
    inviteCode.value = ''
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    joining.value = false
  }
}
</script>

<style scoped>
.class-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--sp-4);
}
.class-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-xs);
}
.class-card__head { display: flex; align-items: flex-start; gap: var(--sp-3); }
.class-card__seal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border: 1px solid var(--brand-300);
  border-radius: var(--r-sm);
  color: var(--color-primary);
  background: var(--color-primary-wash);
}
.class-card__title-wrap { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.class-card__title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.class-card__sub { font-size: var(--fs-xs); color: var(--text-secondary); }
.class-card__meta { margin: 0; font-size: var(--fs-sm); color: var(--text-secondary); }
.search-row { display: flex; gap: var(--sp-2); }
.search-row :deep(.el-input) { flex: 1; }
.search-hint { margin: 0; font-size: var(--fs-xs); color: var(--text-placeholder); }
.member-table { width: 100%; }
.join-hint { margin-top: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
