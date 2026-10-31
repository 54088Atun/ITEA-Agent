import { defineStore } from 'pinia'
import { authApi } from '../api/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('itea_token') || '',
    user: JSON.parse(localStorage.getItem('itea_user') || 'null'),
  }),

  getters: {
    isLoggedIn: (s) => !!s.token,
    role: (s) => s.user?.role || '',
    isTeacher: (s) => s.user?.role === 'teacher',
    isStudent: (s) => s.user?.role === 'student',
    isAdmin: (s) => s.user?.role === 'admin',
    /** 管理员级别；历史空级别按超管兼容，与后端 admin_level_of 一致 */
    adminLevel: (s) => (s.user?.role === 'admin' ? s.user?.admin_level || 'super' : ''),
    isSuperAdmin() {
      return this.adminLevel === 'super'
    },
    isNormalAdmin() {
      return this.adminLevel === 'normal'
    },
    isObserver() {
      return this.adminLevel === 'observer'
    },
    /** 观察者仅可查看，其余管理员可执行写操作 */
    canAdminWrite() {
      return this.isAdmin && this.adminLevel !== 'observer'
    },
    name: (s) => s.user?.name || '',
    /** 登录后的默认首页 */
    homePath: (s) => {
      if (s.user?.role === 'admin') return '/admin/stats'
      if (s.user?.role === 'teacher') return '/teacher'
      return '/student'
    },
  },

  actions: {
    /**
     * 写入登录态
     * 后端返回 {access_token, role, name, user_id, user} —— 扁平字段与 user 对象并存,
     * 两者都要兼容(user 优先,缺失时用扁平字段拼装)
     */
    setAuth(token, data = {}) {
      const user = data.user || {
        id: data.user_id,
        role: data.role,
        name: data.name,
        email: data.email || '',
      }
      this.token = token
      this.user = user
      localStorage.setItem('itea_token', token)
      localStorage.setItem('itea_user', JSON.stringify(user))
    },

    async login(email, password) {
      const data = await authApi.login(email, password)
      this.setAuth(data.access_token, data)
    },

    async register(payload) {
      const data = await authApi.register(
        payload.email, payload.password, payload.name, payload.role
      )
      this.setAuth(data.access_token, data)
    },

    async fetchMe() {
      try {
        const user = await authApi.me()
        this.user = user
        localStorage.setItem('itea_user', JSON.stringify(user))
      } catch {
        this.logout()
      }
    },

    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('itea_token')
      localStorage.removeItem('itea_user')
    },
  },
})
