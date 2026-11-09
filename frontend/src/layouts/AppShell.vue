<template>
  <div class="shell">
    <aside class="shell__side">
      <div class="shell__brand">
        <span class="shell__mark">I</span>
        <span class="shell__brand-text">
          <strong>{{ brand }}</strong>
          <small>{{ brandSub }}</small>
        </span>
      </div>

      <el-menu
        :default-active="activeMenu"
        router
        class="shell__menu"
        background-color="transparent"
        text-color="rgba(255,255,255,0.68)"
        active-text-color="#ffffff"
      >
        <slot name="nav" />
      </el-menu>

      <div class="shell__side-foot">
        <span class="shell__role">{{ roleLabel }}</span>
        <span class="shell__version">ITEA v1.0</span>
      </div>
    </aside>

    <!-- 移动端导航抽屉：复用同一份菜单，避免窄屏只剩 64px 图标栏 -->
    <el-drawer
      v-model="mobileNavOpen"
      direction="ltr"
      size="286px"
      :with-header="false"
      class="shell-nav-drawer"
      modal-class="shell-nav-mask"
    >
      <div class="nav-drawer">
        <div class="nav-drawer__brand">
          <span class="shell__mark">I</span>
          <span class="nav-drawer__brand-text">
            <strong>{{ brand }}</strong>
            <small>{{ brandSub }}</small>
          </span>
        </div>
        <el-menu
          :default-active="activeMenu"
          router
          class="shell__menu nav-drawer__menu"
          background-color="transparent"
          text-color="rgba(255,255,255,0.68)"
          active-text-color="#ffffff"
          @select="closeMobileNav"
        >
          <slot name="nav" />
        </el-menu>
        <div class="nav-drawer__foot">
          <span>{{ roleLabel }}</span>
          <span>ITEA v1.0</span>
        </div>
      </div>
    </el-drawer>

    <div class="shell__main">
      <header class="shell__top">
        <div class="shell__top-left">
          <el-button
            class="shell__nav-btn" text circle aria-label="打开导航菜单"
            @click="mobileNavOpen = true"
          >
            <el-icon :size="20"><Menu /></el-icon>
          </el-button>
          <span class="shell__top-title"><slot name="title">{{ pageTitle }}</slot></span>
        </div>
        <div class="shell__top-right">
          <slot name="actions" />
          <button
            type="button" class="shell__user" title="进入个人中心" aria-label="进入个人中心"
            @click="router.push('/profile')"
          >
            <span class="shell__avatar">
              <img v-if="avatarUrl" :src="resolveAsset(avatarUrl)" alt="" />
              <el-icon v-else :size="15"><User /></el-icon>
            </span>
            <span class="shell__user-text">
              <span class="shell__user-name">{{ userStore.name }}</span>
              <span class="shell__user-role">{{ roleSuffix }}</span>
            </span>
            <el-icon class="shell__user-arrow"><ArrowRight /></el-icon>
          </button>
          <el-button
            class="shell__user-compact" text circle title="个人中心" aria-label="个人中心"
            @click="router.push('/profile')"
          >
            <el-icon><User /></el-icon>
          </el-button>
          <el-button text class="shell__logout" @click="onLogout">
            <el-icon><SwitchButton /></el-icon>
            <span class="shell__logout-text">退出</span>
          </el-button>
        </div>
      </header>

      <main class="shell__content">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Menu, User } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { resolveAsset } from '../utils/asset.js'

defineProps({
  brand: { type: String, default: 'ITEA 智能助教' },
  brandSub: { type: String, default: '高校一体化教学平台' },
  roleLabel: { type: String, default: '' },
  roleSuffix: { type: String, default: '' },
  pageTitle: { type: String, default: '' },
  activeMenu: { type: String, default: '' },
})

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const mobileNavOpen = ref(false)
const avatarUrl = computed(() => userStore.user?.avatar_url || '')

function closeMobileNav() {
  mobileNavOpen.value = false
}

// 移动端抽屉：路由切换后自动收起，避免遮挡新页面
watch(() => route.path, closeMobileNav)

function onLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  background: var(--bg-page);
}

/* ===== 侧栏：深墨蓝渐变 + 顶部光晕，稳重不抢内容 ===== */
.shell__side {
  position: relative;
  width: var(--sidebar-w);
  flex: 0 0 var(--sidebar-w);
  display: flex;
  flex-direction: column;
  background: var(--grad-sidebar);
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  overflow: hidden;
}
/* 侧栏顶部的一团冷光，让纯深色不再是一块死板色块 */
.shell__side::before {
  content: '';
  position: absolute;
  top: -120px;
  left: -60px;
  width: 280px;
  height: 280px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(122, 178, 221, 0.28), transparent 68%);
  pointer-events: none;
}
.shell__brand,
.shell__menu,
.shell__side-foot {
  position: relative;
  z-index: 1;
}

.shell__brand {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  height: var(--topbar-h);
  padding: 0 var(--sp-5);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.shell__mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: var(--r-sm);
  background: var(--grad-accent);
  border: 1px solid rgba(255, 255, 255, 0.28);
  box-shadow: 0 2px 10px rgba(169, 118, 47, 0.35);
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 600;
  color: #fff;
}
.shell__brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}
.shell__brand-text strong {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.shell__brand-text small {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.45);
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.shell__menu {
  flex: 1;
  padding: var(--sp-3) var(--sp-2);
  overflow-y: auto;
}
.shell__menu :deep(.el-menu-item),
.shell__menu :deep(.el-sub-menu__title) {
  height: 42px;
  line-height: 42px;
  margin-bottom: 2px;
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  transition: background-color var(--dur) var(--ease), padding-left var(--dur) var(--ease);
}
.shell__menu :deep(.el-menu-item:hover),
.shell__menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.09);
  color: #fff;
}
/* 仅顶层菜单做 4px 右移反馈，子菜单保持缩进不变，避免 hover 时跳动 */
.shell__menu > :deep(.el-menu-item:hover) {
  padding-left: 24px !important;
}
.shell__menu :deep(.el-menu-item.is-active) {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  font-weight: 600;
  position: relative;
}
.shell__menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 2px;
  border-radius: var(--r-pill);
  background: var(--accent-600);
}
.shell__menu :deep(.el-sub-menu .el-menu) {
  background: transparent;
}
.shell__menu :deep(.el-sub-menu .el-menu-item) {
  padding-left: 46px !important;
  height: 36px;
  line-height: 36px;
}

.shell__side-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.35);
}
.shell__role {
  color: rgba(255, 255, 255, 0.5);
}

/* ===== 顶栏：纸白，仅靠一条细线分隔 ===== */
.shell__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.shell__top {
  height: var(--topbar-h);
  flex: 0 0 var(--topbar-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  padding: 0 var(--sp-6);
  background: var(--bg-topbar);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border);
  position: relative;
  z-index: 2;
}
.shell__top-left {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.02em;
}
.shell__top-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.shell__nav-btn {
  display: none;
  color: var(--text-primary);
  flex: 0 0 auto;
}
.shell__top-right {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.shell__user {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px var(--sp-2) 4px var(--sp-3);
  margin-left: var(--sp-2);
  border: 0;
  border-left: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: inherit;
  font: inherit;
  cursor: pointer;
  transition: background 0.18s ease;
}
.shell__user:hover { background: var(--bg-subtle); }
.shell__user:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.shell__avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  overflow: hidden;
  border-radius: 50%;
  background: var(--bg-subtle);
  color: var(--primary);
  font-size: var(--fs-xs);
  font-weight: 600;
}
.shell__avatar img { width: 100%; height: 100%; object-fit: cover; }
.shell__user-text { display: flex; align-items: center; gap: var(--sp-2); }
.shell__user-arrow { color: var(--text-placeholder); font-size: 12px; }
.shell__user-name {
  font-size: var(--fs-sm);
  color: var(--text-primary);
}
.shell__user-role {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  background: var(--bg-subtle);
  border-radius: 4px;
  padding: 1px 6px;
}
.shell__logout {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}
.shell__user-compact {
  display: none;
}

/* ===== 内容区：统一最大宽度 + 呼吸感留白 ===== */
.shell__content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--sp-5) var(--sp-6) var(--sp-7);
}
.shell__content > :deep(*) {
  max-width: var(--content-max);
  margin: 0 auto;
}

@media (max-width: 1100px) {
  .shell__side {
    width: 64px;
    flex: 0 0 64px;
  }
  .shell__brand-text,
  .shell__side-foot,
  .shell__user {
    display: none;
  }
  .shell__brand {
    justify-content: center;
    padding: 0;
  }
  .shell__menu {
    padding: var(--sp-3) var(--sp-1);
  }
  /* 仅收起左侧图标栏的文字，抽屉内仍显示完整菜单名 */
  .shell__side .shell__menu :deep(.el-menu-item span) {
    display: none;
  }
  /* 窄屏保留紧凑个人中心入口,不恢复占宽的完整胶囊 */
  .shell__user-compact {
    display: inline-flex;
  }
}

/* ===== 手机端：隐藏图标栏，改为抽屉导航 ===== */
@media (max-width: 767px) {
  .shell__side {
    display: none;
  }
  .shell__nav-btn {
    display: inline-flex;
    margin-left: -4px;
  }
  .shell__top {
    gap: var(--sp-2);
    padding: 0 var(--sp-3);
    height: calc(var(--topbar-h) - 6px);
    flex-basis: calc(var(--topbar-h) - 6px);
  }
  .shell__top-left {
    font-size: var(--fs-base);
  }
  .shell__top-right {
    gap: var(--sp-1);
  }
  .shell__logout {
    padding: 0 var(--sp-2);
  }
  .shell__logout-text {
    display: none;
  }
  .shell__user-compact {
    display: inline-flex;
  }
  .shell__content {
    padding: var(--sp-4) var(--sp-3)
      calc(var(--sp-6) + env(safe-area-inset-bottom, 0px));
  }
}

/* 抽屉挂在 body 下，需用全局选择器覆盖 Element Plus 默认白底 */
:global(.shell-nav-drawer) {
  background: var(--grad-sidebar);
  max-width: 82vw;
}
:global(.shell-nav-drawer .el-drawer__body) {
  padding: 0;
  overflow: hidden;
}
:global(.shell-nav-mask) {
  backdrop-filter: blur(2px);
}

.nav-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  color: #fff;
}
.nav-drawer__brand {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: calc(var(--sp-5) + env(safe-area-inset-top, 0px)) var(--sp-5) var(--sp-4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.nav-drawer__brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.3;
}
.nav-drawer__brand-text strong {
  font-size: var(--fs-base);
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
}
.nav-drawer__brand-text small {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.45);
  white-space: nowrap;
}
.nav-drawer__menu {
  flex: 1;
  padding: var(--sp-3) var(--sp-2);
  overflow-y: auto;
}
.nav-drawer__menu :deep(.el-menu-item),
.nav-drawer__menu :deep(.el-sub-menu__title) {
  height: 46px;
  line-height: 46px;
  margin-bottom: 2px;
  border-radius: var(--r-sm);
  font-size: var(--fs-base);
  color: rgba(255, 255, 255, 0.72);
}
.nav-drawer__menu :deep(.el-menu-item.is-active) {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  font-weight: 600;
}
.nav-drawer__menu :deep(.el-sub-menu .el-menu-item) {
  padding-left: 46px !important;
  height: 40px;
  line-height: 40px;
}
.nav-drawer__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-5)
    calc(var(--sp-3) + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.4);
}
</style>
