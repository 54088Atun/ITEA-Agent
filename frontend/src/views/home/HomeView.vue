<template>
  <div class="home">
    <header :class="['home-nav', { 'home-nav--scrolled': scrolled }]">
      <div class="hp-container home-nav__inner">
        <router-link to="/" class="home-nav__brand" aria-label="ITEA-Agent 首页">
          <span class="home-nav__mark">I</span>
          <span class="home-nav__name">ITEA-Agent</span>
        </router-link>

        <nav class="home-nav__links" aria-label="主导航">
          <template v-for="link in nav.links" :key="link.label">
            <router-link v-if="link.to" :to="link.to">{{ link.label }}</router-link>
            <a v-else :href="link.href">{{ link.label }}</a>
          </template>
        </nav>

        <div class="home-nav__actions">
          <router-link :to="nav.login.to" class="hp-btn hp-btn--quiet">{{ nav.login.label }}</router-link>
          <router-link :to="nav.cta.to" class="hp-btn hp-btn--primary">{{ nav.cta.label }}</router-link>
        </div>

        <button
          type="button"
          class="home-nav__toggle"
          :aria-expanded="menuOpen"
          aria-controls="home-mobile-menu"
          aria-label="打开导航菜单"
          @click="menuOpen = !menuOpen"
        >
          <el-icon><component :is="menuOpen ? 'Close' : 'Menu'" /></el-icon>
        </button>
      </div>

      <div v-show="menuOpen" id="home-mobile-menu" class="home-nav__mobile">
        <template v-for="link in nav.links" :key="link.label">
          <router-link v-if="link.to" :to="link.to" @click="menuOpen = false">
            {{ link.label }}
          </router-link>
          <a v-else :href="link.href" @click="menuOpen = false">{{ link.label }}</a>
        </template>
        <router-link :to="nav.login.to" class="hp-btn hp-btn--ghost" @click="menuOpen = false">
          {{ nav.login.label }}
        </router-link>
        <router-link :to="nav.cta.to" class="hp-btn hp-btn--primary" @click="menuOpen = false">
          {{ nav.cta.label }}
        </router-link>
      </div>
    </header>

    <main>
      <HeroSection />
      <FactStrip />
      <ShowcaseCarousel v-reveal />
      <RolePaths v-reveal />
      <AgentFlow v-reveal />
      <CapabilityGrid v-reveal />
      <TrustSection v-reveal />
      <SceneFaq v-reveal />
      <ClosingCta />
    </main>

    <footer class="home-foot">
      <div class="hp-container home-foot__inner">
        <div class="home-foot__brand">
          <div class="home-nav__brand">
            <span class="home-nav__mark">I</span>
            <span class="home-nav__name">{{ footer.brand }}</span>
          </div>
          <p>{{ footer.desc }}</p>
        </div>

        <nav
          v-for="column in footer.columns"
          :key="column.title"
          class="home-foot__col"
          :aria-label="column.title"
        >
          <h3>{{ column.title }}</h3>
          <template v-for="link in column.links" :key="link.label">
            <router-link v-if="link.to" :to="link.to">{{ link.label }}</router-link>
            <a v-else :href="link.href">{{ link.label }}</a>
          </template>
        </nav>
      </div>

      <div class="hp-container home-foot__bottom">
        <span>{{ footer.copyright }}</span>
        <span>Intelligent Teaching Ecosystem Assistant</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { nav, footer } from './content'
import { useSiteStore } from '../../stores/site'
import { reveal } from '../../directives/reveal'
import HeroSection from './sections/HeroSection.vue'
import FactStrip from './sections/FactStrip.vue'
import ShowcaseCarousel from './sections/ShowcaseCarousel.vue'
import RolePaths from './sections/RolePaths.vue'
import AgentFlow from './sections/AgentFlow.vue'
import CapabilityGrid from './sections/CapabilityGrid.vue'
import TrustSection from './sections/TrustSection.vue'
import SceneFaq from './sections/SceneFaq.vue'
import ClosingCta from './sections/ClosingCta.vue'
import './home.css'

const vReveal = reveal

const scrolled = ref(false)
const menuOpen = ref(false)
const siteStore = useSiteStore()

function onScroll() {
  scrolled.value = window.scrollY > 80
}

onMounted(() => {
  onScroll()
  window.addEventListener('scroll', onScroll, { passive: true })
  siteStore.ensure()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.home {
  min-height: 100%;
  background: var(--bg-page);
}

/* ===== 顶部导航 ===== */
.home-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid transparent;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease);
}

.home-nav--scrolled {
  background: var(--bg-topbar);
  backdrop-filter: blur(12px);
  border-bottom-color: var(--border);
  box-shadow: var(--shadow-xs);
}

.home-nav__inner {
  display: flex;
  align-items: center;
  gap: var(--sp-6);
  height: 64px;
}

.home-nav__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--text-primary);
}

.home-nav__mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--r-sm);
  border: 1px solid rgba(169, 118, 47, 0.55);
  background: var(--brand-900);
  font-family: var(--font-serif);
  font-size: 17px;
  color: var(--accent-100);
}

.home-nav__name {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.home-nav__links {
  display: flex;
  gap: var(--sp-6);
  margin-left: var(--sp-4);
}

.home-nav__links a {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  transition: color var(--dur-fast) var(--ease);
}

.home-nav__links a:hover {
  color: var(--color-primary);
}

.home-nav__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-left: auto;
}

.home-nav__actions .hp-btn {
  height: 36px;
  padding: 0 var(--sp-4);
  font-size: var(--fs-sm);
}

.home-nav__toggle {
  display: none;
  margin-left: auto;
  width: 38px;
  height: 38px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  background: var(--bg-card);
  color: var(--text-primary);
  font-size: 18px;
}

.home-nav__mobile {
  display: none;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-5) var(--sp-5);
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}

.home-nav__mobile a:not(.hp-btn) {
  padding: var(--sp-2) 0;
  font-size: var(--fs-base);
  color: var(--text-primary);
}

/* ===== 页脚 ===== */
.home-foot {
  border-top: 1px solid var(--border);
  background: var(--bg-subtle);
}

.home-foot__inner {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(3, minmax(0, 1fr));
  gap: var(--sp-7);
  padding-top: var(--sp-9);
  padding-bottom: var(--sp-8);
}

.home-foot__brand p {
  margin-top: var(--sp-3);
  max-width: 280px;
  font-size: var(--fs-xs);
  line-height: 1.8;
  color: var(--text-secondary);
}

.home-foot__col {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.home-foot__col h3 {
  margin-bottom: var(--sp-2);
  font-size: var(--fs-xs);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-primary);
}

.home-foot__col a {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.home-foot__col a:hover {
  color: var(--color-primary);
}

.home-foot__bottom {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-top: var(--sp-5);
  padding-bottom: var(--sp-6);
  border-top: 1px solid var(--border);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-placeholder);
}

@media (max-width: 960px) {
  .home-nav__links,
  .home-nav__actions {
    display: none;
  }

  .home-nav__toggle {
    display: grid;
    place-items: center;
  }

  .home-nav__mobile {
    display: flex;
  }

  .home-foot__inner {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-6);
  }

  .home-foot__brand {
    grid-column: span 2;
  }
}

@media (max-width: 767px) {
  .home-foot__inner {
    grid-template-columns: 1fr;
    padding-top: var(--sp-7);
  }

  .home-foot__brand {
    grid-column: auto;
  }

  .home-foot__bottom {
    flex-direction: column;
  }
}
</style>
