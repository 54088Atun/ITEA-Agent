import { onBeforeUnmount, watch } from 'vue'

/**
 * 长列表增量加载：哨兵进入视口时触发 loadMore。
 * 用于日志审计 / 运行回放等可能超过百条的列表，避免一次性渲染全部行。
 *
 * @param {import('vue').Ref<HTMLElement|null>} sentinelRef 列表底部哨兵
 * @param {() => boolean} canLoadMore 是否还有下一页
 * @param {() => void} loadMore 加载下一页
 */
export function useAutoLoadMore(sentinelRef, canLoadMore, loadMore, options = {}) {
  const { rootMargin = '240px' } = options
  let observer = null

  function disconnect() {
    if (observer) {
      observer.disconnect()
      observer = null
    }
  }

  watch(sentinelRef, (el) => {
    disconnect()
    if (!el || typeof IntersectionObserver === 'undefined') return
    observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting) && canLoadMore()) {
        loadMore()
      }
    }, { rootMargin })
    observer.observe(el)
  }, { flush: 'post' })

  onBeforeUnmount(disconnect)
}
