<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">智能助手</h2>
        <p class="page-sub">只读汇总平台用户、课程审核、知识点、素材与风控日志，提供数据解读与治理建议</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="newSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
    </div>

    <el-alert
      class="assistant-tip"
      type="info"
      :closable="false"
      show-icon
      title="小助手只提供分析建议，不会执行任何业务变更；实际写操作请按权限在对应页面完成。"
    />

    <div class="chat-container">
      <ChatWindow
        :key="sessionKey"
        welcome="你好!我是平台管理助手,可以帮你梳理用户构成、课程审核进度、风险日志与治理建议。"
        placeholder="例如:汇总一下平台用户构成和待审核课程..."
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
  '汇总平台用户与角色分布',
  '统计各审核状态的课程数量',
  '最近的风险日志情况如何',
  '给出账号与课程的治理建议',
]

function newSession() {
  sessionKey.value++ // 销毁重建 ChatWindow,清空会话
}
</script>

<style scoped>
.assistant-tip {
  margin-bottom: var(--sp-3);
}
.chat-container { flex: 1; min-height: 0; }
</style>
