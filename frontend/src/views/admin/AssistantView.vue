<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">智能助手</h2>
        <p class="page-sub">直接下达任务或询问数据，执行结果会写入操作审计</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="newSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
    </div>

    <div class="chat-container">
      <ChatWindow
        :key="sessionKey"
        welcome="我是平台管理助手。可以直接让我审核课程、启停账号、重置密码、改配置或清理上传文件，也能帮你解读平台数据。"
        placeholder="给平台管理助手发送消息，例如：汇总用户与课程审核状态"
        assistant-name="平台管理助手"
        endpoint="/api/admin/chat/stream"
        :suggestions="suggestions"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ChatWindow from '../../components/ChatWindow.vue'

const sessionKey = ref(0)

const suggestions = [
  '汇总平台用户与课程审核状态',
  '把待审核课程全部通过',
  '清理过期的上传文件',
  '把配置项 maintenance_notice 设置为：今晚 22:00 停机维护',
]

function newSession() {
  sessionKey.value++ // 销毁重建 ChatWindow,清空会话
}
</script>

<style scoped>
.chat-container {
  flex: 1;
  min-height: 0;
}
</style>
