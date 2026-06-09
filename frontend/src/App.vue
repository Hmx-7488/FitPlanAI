<script setup lang="ts">
import { onMounted, useTemplateRef } from 'vue'
import gsap from 'gsap'

// 跨导航保持状态的视图：分析过程中切换 tab 不丢失进度
const cachedViews: string[] = ['BodyPhotoView', 'PoseView', 'MealView']

const headerRef = useTemplateRef<HTMLElement>('headerRef')

onMounted(() => {
  if (headerRef.value) {
    const links = headerRef.value.querySelectorAll('.nav-link')
    gsap.from(headerRef.value, {
      y: -20,
      duration: 0.5,
      ease: 'power3.out',
      onComplete: () => gsap.set(headerRef.value, { clearProps: 'transform' }),
      onInterrupt: () => gsap.set(headerRef.value, { clearProps: 'transform' }),
    })
    gsap.from(links, {
      y: -10, opacity: 0, stagger: 0.04, duration: 0.3, ease: 'power2.out', delay: 0.2,
      onComplete: () => gsap.set(links, { clearProps: 'transform,opacity' }),
      onInterrupt: () => gsap.set(links, { clearProps: 'transform,opacity' }),
    })
  }
})
// 页面级过渡使用纯 CSS，GSAP 仅用于各视图内部元素动画
</script>

<template>
  <div class="app-shell">
    <header class="app-header" ref="headerRef">
      <div class="header-inner">
        <router-link to="/" class="brand">
          <span class="brand-mark">&#9679;</span>
          <span class="brand-text">SlimAgent</span>
        </router-link>
        <nav class="nav">
          <router-link to="/" class="nav-link" exact-active-class="nav-link--active">首页</router-link>
          <router-link to="/profile" class="nav-link" active-class="nav-link--active">建档</router-link>
          <router-link to="/analysis" class="nav-link" active-class="nav-link--active">分析</router-link>
          <router-link to="/plan" class="nav-link" active-class="nav-link--active">计划</router-link>
          <router-link to="/food" class="nav-link" active-class="nav-link--active">食材</router-link>
          <router-link to="/meal" class="nav-link" active-class="nav-link--active">餐食</router-link>
          <router-link to="/body-photo" class="nav-link" active-class="nav-link--active">身材</router-link>
          <router-link to="/pose" class="nav-link" active-class="nav-link--active">动作</router-link>
          <router-link to="/checkin" class="nav-link" active-class="nav-link--active">打卡</router-link>
          <router-link to="/history" class="nav-link" active-class="nav-link--active">复盘</router-link>
        </nav>
      </div>
    </header>
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <keep-alive :include="cachedViews">
            <component :is="Component" />
          </keep-alive>
        </transition>
      </router-view>
    </main>
  </div>
</template>

<style>
/* 非 scoped：transition class 作用于子组件 DOM，纯 CSS 驱动 */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.2s ease;
}
.page-enter-from,
.page-leave-to {
  opacity: 0;
}
</style>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: oklch(1 0 0 / 0.85);
  border-bottom: 1px solid var(--color-border-subtle);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.header-inner {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-6);
  height: 56px;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  text-decoration: none;
  color: var(--color-text-primary);
  font-weight: 700;
  font-size: var(--text-lg);
  letter-spacing: -0.02em;
}

.brand-mark {
  color: var(--color-accent);
  font-size: 10px;
  line-height: 1;
}

.brand-text {
  font-family: var(--font-mono);
  font-size: var(--text-md);
  letter-spacing: 0.04em;
}

.nav {
  display: flex;
  gap: var(--space-1);
  min-width: 0;
}

.nav-link {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  text-decoration: none;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-secondary);
  transition: color var(--duration-fast) var(--ease-out),
              background-color var(--duration-fast) var(--ease-out);
}

.nav-link:hover {
  color: var(--color-text-primary);
  background-color: var(--color-accent-subtle);
}

.nav-link--active {
  color: var(--color-accent);
  background-color: var(--color-accent-subtle);
}

.app-main {
  flex: 1;
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6);
}

@media (max-width: 720px) {
  .header-inner {
    width: 100%;
    padding: 0 var(--space-3);
    gap: var(--space-3);
  }

  .brand {
    flex: 0 0 auto;
  }

  .nav {
    flex: 1 1 auto;
    overflow-x: auto;
    overscroll-behavior-inline: contain;
    scrollbar-width: none;
  }

  .nav::-webkit-scrollbar {
    display: none;
  }

  .nav-link {
    flex: 0 0 auto;
    padding: var(--space-2);
    font-size: var(--text-sm);
  }

  .app-main {
    padding: var(--space-6) var(--space-4);
  }
}
</style>
