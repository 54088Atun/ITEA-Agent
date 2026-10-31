<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">课程助教</h2>
        <p class="page-sub">引导式答疑 —— 不选课程也可以问通用知识，选择课程后会结合该课程资料与你的学情</p>
      </div>
      <div class="page-head__actions">
        <el-select
          v-model="courseId"
          placeholder="选择课程（可选）"
          clearable
          style="width: 220px"
          @change="newSession"
        >
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button @click="joinVisible = true">
          <el-icon><UserFilled /></el-icon> 加入班级
        </el-button>
        <el-button @click="newSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!courses.length"
      class="tip"
      type="info"
      :closable="false"
      show-icon
      title="还没有课程：输入教师提供的班级邀请码加入后，就能看到该班级课程与资料。"
    />

    <div class="chat-container">
      <ChatWindow
        :key="sessionKey"
        welcome="你好!我是你的课程助教。可以选择课程后结合课程资料提问，也可以直接问课堂以外的知识。"
        placeholder="例如:二叉树的前序遍历和中序遍历有什么区别?或者贴上你的报错代码..."
        :course-id="courseId || null"
        branch="tutor"
        :suggestions="suggestions"
      />
    </div>

    <el-dialog v-model="joinVisible" title="加入班级" width="420px">
      <el-input v-model="inviteCode" placeholder="输入教师提供的邀请码" @keyup.enter="join" />
      <p class="join-hint">加入后会自动获得该班级课程的访问权限。</p>
      <template #footer>
        <el-button @click="joinVisible = false">取消</el-button>
        <el-button type="primary" :loading="joining" @click="join">加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import ChatWindow from '../../components/ChatWindow.vue'
import { courseApi } from '../../api/course'
import { classroomApi } from '../../api/classroom'

const courses = ref([])
const courseId = ref(null)
const sessionKey = ref(0)

const joinVisible = ref(false)
const joining = ref(false)
const inviteCode = ref('')

const suggestions = [
  '帮我梳理这门课的知识框架',
  '这道题我卡住了，能给我一点提示吗',
  '解释一下这段代码报错的原因',
]

onMounted(loadCourses)

async function loadCourses() {
  try {
    // /course/list 直接返回数组(已按选课关系过滤)
    const data = await courseApi.list()
    courses.value = Array.isArray(data) ? data : []
  } catch { /* 拦截器已提示 */ }
}

function newSession() {
  sessionKey.value++
}

async function join() {
  const code = inviteCode.value.trim()
  if (!code) return ElMessage.warning('请输入邀请码')
  joining.value = true
  try {
    const data = await classroomApi.join(code)
    ElMessage.success(`已加入班级：${data.class_name}`)
    joinVisible.value = false
    inviteCode.value = ''
    await loadCourses()
    if (data.course_id) {
      courseId.value = data.course_id
      newSession()
    }
  } catch { /* 拦截器已提示 */ } finally {
    joining.value = false
  }
}
</script>

<style scoped>
.chat-container { flex: 1; min-height: 0; }
.tip { border-radius: var(--r-sm); }
.join-hint {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
</style>
