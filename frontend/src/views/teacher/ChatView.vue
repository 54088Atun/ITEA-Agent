<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">备课助手</h2>
        <p class="page-sub">教学大纲、教案框架、课堂活动与练习设计，均可对话生成</p>
      </div>
      <div class="page-head__actions">
        <el-select v-model="courseId" placeholder="选择课程" filterable style="width: 220px" @change="onCourseChange">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button @click="newSession">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
      </div>
    </div>

    <div class="chat-container">
      <ChatWindow
        v-if="courseId"
        ref="chatRef"
        :key="sessionKey"
        welcome="你好!我是备课助手,可以帮你设计教学大纲、生成教案框架、规划课堂活动。"
        placeholder="例如:帮我设计《数据结构》第3章二叉树的教学框架..."
        :course-id="courseId"
        branch="teacher"
        :suggestions="suggestions"
      />
      <StateBlock
        v-else
        state="empty"
        title="请先选择课程"
        hint="选择课程后即可让备课助手生成教学大纲与课堂活动"
        class="empty-center"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import ChatWindow from '../../components/ChatWindow.vue'
import StateBlock from '../../components/StateBlock.vue'
import { teacherApi } from '../../api/teacher'

const courses = ref([])
const courseId = ref(null)
const sessionKey = ref(0)
const chatRef = ref()

const suggestions = [
  '帮我设计本章的教学框架',
  '生成一组课堂讨论的引导问题',
  '为这个知识点出一道随堂练习',
]

onMounted(async () => {
  try {
    // /teacher/courses 直接返回数组
    const data = await teacherApi.courses()
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) courseId.value = courses.value[0].id
  } catch { /* 拦截器已提示 */ }
})

function onCourseChange() {
  newSession()
}

function newSession() {
  sessionKey.value++ // 销毁重建 ChatWindow,清空会话
}
</script>

<style scoped>
.chat-container { flex: 1; min-height: 0; }
.empty-center { height: 100%; display: flex; align-items: center; justify-content: center; }

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
