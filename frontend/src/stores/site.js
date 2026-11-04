import { defineStore } from 'pinia'
import { siteApi } from '../api/site'
import { applyHomeConfig } from '../views/home/content'
import { applyContactConfig } from '../views/contact/content'

/**
 * 站点内容:后台保存的首页与联系页文案
 * 读取失败时保持内置默认文案,不阻塞页面渲染
 */
export const useSiteStore = defineStore('site', {
  state: () => ({
    loaded: false,
    loading: false,
  }),

  actions: {
    async ensure() {
      if (this.loaded || this.loading) return
      this.loading = true
      try {
        const data = await siteApi.content()
        applyHomeConfig(data?.home)
        applyContactConfig(data?.contact)
        this.loaded = true
      } catch {
        // 文案接口不可用时使用内置内容
      } finally {
        this.loading = false
      }
    },

    async reload() {
      this.loaded = false
      await this.ensure()
    },
  },
})
