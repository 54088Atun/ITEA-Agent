<template>
  <AppShell
    brand="ITEA 智能助教"
    brand-sub="教师工作台"
    role-label="教师端"
    role-suffix="老师"
    page-title="教师工作台"
    :active-menu="activeMenu"
  >
    <template #nav>
      <el-menu-item index="/teacher/courses">
        <el-icon><Reading /></el-icon>
        <span>课程管理</span>
      </el-menu-item>
      <el-menu-item index="/teacher/classes">
        <el-icon><UserFilled /></el-icon>
        <span>班级管理</span>
      </el-menu-item>
      <el-menu-item v-if="features.feature_assignments" index="/teacher/assignments">
        <el-icon><EditPen /></el-icon>
        <span>作业与考试</span>
      </el-menu-item>
      <el-menu-item v-if="features.feature_exams" index="/teacher/questions">
        <el-icon><Collection /></el-icon>
        <span>题库与组卷</span>
      </el-menu-item>
      <el-menu-item index="/teacher/chat">
        <el-icon><ChatDotRound /></el-icon>
        <span>备课助手</span>
      </el-menu-item>
      <el-menu-item index="/teacher/report">
        <el-icon><DataAnalysis /></el-icon>
        <span>班级看板</span>
      </el-menu-item>
      <el-menu-item index="/contact">
        <el-icon><Service /></el-icon>
        <span>联系我们</span>
      </el-menu-item>
      <el-menu-item v-if="userStore.isAdmin" index="/admin/stats">
        <el-icon><Monitor /></el-icon>
        <span>管理后台</span>
      </el-menu-item>
    </template>

    <router-view />
  </AppShell>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './AppShell.vue'
import { useUserStore } from '../stores/user'
import { features, loadFeatures } from '../stores/features'

const route = useRoute()
const userStore = useUserStore()

onMounted(loadFeatures)

const activeMenu = computed(() => {
  // 课程详情页高亮"课程管理"
  if (route.path.startsWith('/teacher/course/')) return '/teacher/courses'
  return route.path
})
</script>
