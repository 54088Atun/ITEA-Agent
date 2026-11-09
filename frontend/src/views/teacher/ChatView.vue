<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">智能助手</h2>
        <p class="page-sub">课程、班级、作业、考试与教学资料，都可以在这里统一查询和处理</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="newSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
    </div>

    <div class="chat-container">
      <ChatWindow
        ref="chatRef"
        :key="sessionKey"
        welcome="你好!我是智能助手,可以查询你的课程、班级、作业与考试,也能帮你修改课程信息、建班、发作业、录入题目等。"
        placeholder="例如:我有哪些班级?帮我给这个班加一条公告;为课程新增一道单选题..."
        :course-id="null"
        branch="teacher"
        :suggestions="suggestions"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ChatWindow from '../../components/ChatWindow.vue'

const sessionKey = ref(0)
const chatRef = ref()

const suggestions = [
  '我目前有哪些课程和班级?',
  '帮我给课程新建一个班级',
  '查看这个班最近的作业提交情况',
]

function newSession() {
  sessionKey.value++ // 销毁重建 ChatWindow,清空会话
}
</script>

<style scoped>
.chat-container { flex: 1; min-height: 0; }

@media (max-width: 767px) {
  .page-head__main .page-sub {
    display: none;
  }
  .page-head__actions {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: none;
  }
  .page-head__actions::-webkit-scrollbar {
    display: none;
  }
  .page-head__actions :deep(.el-select) {
    flex: 1 1 auto;
    width: auto !important;
    min-width: 0;
  }
  .page-head__actions :deep(.el-button) {
    flex: 0 0 auto;
    white-space: nowrap;
  }
}
</style>
