import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/auth/LoginView.vue'),
    meta: { public: true },
  },
  // ===== 教师端 =====
  {
    path: '/teacher',
    component: () => import('../layouts/TeacherLayout.vue'),
    meta: { role: 'teacher' },
    children: [
      { path: '', redirect: '/teacher/courses' },
      { path: 'courses', name: 'teacher-courses', component: () => import('../views/teacher/CourseListView.vue') },
      { path: 'classes', name: 'teacher-classes', component: () => import('../views/teacher/ClassesView.vue') },
      { path: 'assignments', name: 'teacher-assignments', component: () => import('../views/teacher/AssignmentsView.vue') },
      { path: 'questions', name: 'teacher-questions', component: () => import('../views/teacher/QuestionBankView.vue') },
      { path: 'course/:id', name: 'teacher-course-detail', component: () => import('../views/teacher/CourseDetailView.vue') },
      { path: 'chat', name: 'teacher-chat', component: () => import('../views/teacher/ChatView.vue') },
      { path: 'report', name: 'teacher-report', component: () => import('../views/teacher/ReportView.vue') },
    ],
  },
  // ===== 学生端 =====
  {
    path: '/student',
    component: () => import('../layouts/StudentLayout.vue'),
    meta: { role: 'student' },
    children: [
      { path: '', redirect: '/student/tutor' },
      { path: 'tutor', name: 'student-tutor', component: () => import('../views/student/TutorView.vue') },
      { path: 'assignments', name: 'student-assignments', component: () => import('../views/student/AssignmentsView.vue') },
      { path: 'exams', name: 'student-exams', component: () => import('../views/student/ExamsView.vue') },
      { path: 'wrong', name: 'student-wrong', component: () => import('../views/student/WrongView.vue') },
      { path: 'review', name: 'student-review', component: () => import('../views/student/ReviewView.vue') },
      { path: 'interview', name: 'student-interview', component: () => import('../views/student/InterviewView.vue') },
      { path: 'progress', name: 'student-progress', component: () => import('../views/student/ProgressView.vue') },
    ],
  },
  // ===== 管理端 =====
  {
    path: '/admin',
    component: () => import('../layouts/AdminLayout.vue'),
    meta: { role: 'admin' },
    children: [
      { path: '', redirect: '/admin/stats' },
      { path: 'stats', name: 'admin-stats', component: () => import('../views/admin/PlatformStats.vue') },
      { path: 'assistant', name: 'admin-assistant', component: () => import('../views/admin/AssistantView.vue') },
      { path: 'users', name: 'admin-users', component: () => import('../views/admin/UserManage.vue') },
      { path: 'courses', name: 'admin-courses', component: () => import('../views/admin/CourseAudit.vue') },
      { path: 'risk', name: 'admin-risk', component: () => import('../views/admin/RiskAudit.vue') },
      { path: 'logs', name: 'admin-logs', component: () => import('../views/admin/LogAudit.vue') },
      { path: 'config', name: 'admin-config', component: () => import('../views/admin/SystemConfig.vue') },
    ],
  },
  { path: '/', redirect: '/login' },
  // 个人中心:所有已登录角色共用
  {
    path: '/profile',
    name: 'profile',
    component: () => import('../views/common/ProfileView.vue'),
  },
  { path: '/:pathMatch(.*)*', redirect: '/login' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 导航守卫:登录校验 + 角色隔离(admin 为超集角色)
router.beforeEach((to) => {
  const store = useUserStore()

  if (to.meta.public) {
    // 已登录访问登录页 → 跳转对应首页
    if (store.isLoggedIn) return store.homePath
    return true
  }

  if (!store.isLoggedIn) return '/login'

  // 角色隔离:admin 可访问教师/学生端,其余角色只能进自己的入口
  const needRole = to.meta.role
  if (needRole && store.role !== needRole && !store.isAdmin) {
    return store.homePath
  }
  return true
})

export default router
