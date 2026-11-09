<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">智能助手</h2>
        <p class="page-sub">课程学习、班级事务、作业考试，都可以直接问我</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="joinVisible = true">
          <el-icon><UserFilled /></el-icon> 加入班级
        </el-button>
        <el-button @click="newSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
    </div>

    <div class="chat-container">
      <ChatWindow
        :key="sessionKey"
        welcome="你好!我是你的智能助手。可以问我学习问题，也可以查询班级、作业和考试，还能帮你提交作业。"
        placeholder="例如:二叉树的前序遍历和中序遍历有什么区别?或者贴上你的报错代码..."
        :course-id="null"
        branch="tutor"
        :suggestions="suggestions"
      />
    </div>

    <el-dialog v-model="joinVisible" title="使用课程码加入" width="420px">
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
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import ChatWindow from '../../components/ChatWindow.vue'
import { codeApi } from '../../api/codes'

const sessionKey = ref(0)

const joinVisible = ref(false)
const joining = ref(false)
const inviteCode = ref('')

const suggestions = [
  '我有哪些作业还没提交?',
  '帮我看看这周有哪些考试',
  '这个班里有我的课代表吗',
]

function newSession() {
  sessionKey.value++
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

/* 手机端：对话页优先保证气泡区域高度，工具栏改为单行横向滑动 */
@media (max-width: 767px) {
  .page-head__main .page-sub {
    display: none;
  }
  .page-head__actions {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: none;
    -webkit-overflow-scrolling: touch;
  }
  .page-head__actions::-webkit-scrollbar {
    display: none;
  }
  .page-head__actions :deep(.el-select) {
    flex: 0 0 150px;
    width: 150px !important;
  }
  .page-head__actions :deep(.el-checkbox),
  .page-head__actions :deep(.el-button) {
    flex: 0 0 auto;
    white-space: nowrap;
  }
}
</style>
