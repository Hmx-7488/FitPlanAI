<script setup lang="ts">
import { ref, onMounted, computed, nextTick, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { getDashboard, type DashboardData } from '../api'
import { heroEntrance, dashboardEntrance, flowStepsEntrance, progressFillIn, countUp } from '../utils/animations'

const router = useRouter()
const loading = ref(true)
const data = ref<DashboardData | null>(null)
const hasProfile = ref(false)
const loadError = ref(false)
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const consumedRef = useTemplateRef<HTMLElement>('consumedRef')
const streakRef = useTemplateRef<HTMLElement>('streakRef')
const weightRef = useTemplateRef<HTMLElement>('weightRef')
const progressRef = useTemplateRef<HTMLElement>('progressRef')

const calorieStatus = computed(() => {
  if (!data.value) return { label: '未知', color: 'var(--color-text-tertiary)' }
  const pct = data.value.meal_summary.progress_pct
  if (pct < 30) return { label: '刚开始', color: 'var(--color-accent)' }
  if (pct < 80) return { label: '进行中', color: 'var(--color-accent)' }
  if (pct < 100) return { label: '接近目标', color: 'var(--color-warning)' }
  return { label: '已达标', color: 'oklch(0.55 0.18 25)' }
})

const goalLabel = computed(() => {
  if (!data.value) return ''
  return data.value.profile.goal_type === 'muscle_gain' ? '增肌' : '减脂'
})

const weightDiff = computed(() => {
  if (!data.value) return 0
  return +(data.value.profile.weight - data.value.profile.target_weight).toFixed(1)
})

/** 动态步骤引导：根据用户当前状态判断下一步该做什么 */
const steps = computed(() => {
  if (!data.value) return []
  const d = data.value
  const hasPlan = !!d.latest_plan
  const todayChecked = d.checkin_summary.today_checked
  const totalDays = d.checkin_summary.total_days

  const list = [
    {
      label: '完成建档',
      done: true,
      route: '/profile',
      icon: '✅',
    },
    {
      label: hasPlan ? '生成计划' : '生成计划',
      done: hasPlan,
      route: '/plan',
      icon: hasPlan ? '✅' : '⬜',
      action: hasPlan ? '已完成' : '去生成',
    },
    {
      label: '今日打卡',
      done: todayChecked,
      route: '/checkin',
      icon: todayChecked ? '✅' : '⬜',
      action: todayChecked ? '已完成' : '去打卡',
    },
    {
      label: '查看 AI 复盘',
      done: false,
      route: '/history',
      icon: totalDays >= 3 ? '⬜' : '🔒',
      action: totalDays >= 3 ? '去复盘' : `需${totalDays}/3天打卡`,
      locked: totalDays < 3,
    },
  ]
  return list
})

async function loadDashboard() {
  const userId = localStorage.getItem('userId')
  if (!userId) {
    hasProfile.value = false
    loading.value = false
    await nextTick()
    if (pageRef.value) heroEntrance(pageRef.value)
    await nextTick()
    if (pageRef.value) flowStepsEntrance(pageRef.value)
    return
  }
  loading.value = true
  loadError.value = false
  try {
    data.value = await getDashboard(Number(userId))
    hasProfile.value = true
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      localStorage.removeItem('userId')
      hasProfile.value = false
    } else {
      loadError.value = true
    }
  } finally {
    loading.value = false
    await nextTick()
    if (!pageRef.value || loadError.value) return
    if (hasProfile.value && data.value) {
      dashboardEntrance(pageRef.value)
      if (consumedRef.value) countUp(consumedRef.value, data.value.meal_summary.consumed_kcal)
      if (streakRef.value) countUp(streakRef.value, data.value.checkin_summary.streak, { suffix: '' })
      if (weightRef.value) countUp(weightRef.value, data.value.checkin_summary.latest_weight, { suffix: '', duration: 1 })
      if (progressRef.value) progressFillIn(progressRef.value, data.value.meal_summary.progress_pct)
    } else {
      heroEntrance(pageRef.value)
      flowStepsEntrance(pageRef.value)
    }
  }
}

onMounted(loadDashboard)
</script>

<template>
  <div class="home" ref="pageRef">
    <!-- 加载失败 -->
    <section v-if="!loading && loadError" class="load-error">
      <h1 class="load-error-title">数据加载失败</h1>
      <p class="load-error-desc">无法连接后端服务或数据暂时不可用。<br>你的档案和打卡记录都还在，请稍后重试。</p>
      <button class="btn btn-primary" @click="loadDashboard">重新加载</button>
    </section>

    <!-- 未建档：引导页 -->
    <template v-if="!loading && !hasProfile && !loadError">
      <section class="hero">
        <p class="hero-eyebrow">基于 Agentic RAG 的智能减脂教练</p>
        <h1 class="hero-title">吃对了，练对了，<br>脂肪自然就掉了。</h1>
        <p class="hero-sub">输入身体数据，AI 生成饮食和运动计划。<br>每天打卡，自动复盘并调整方案。</p>
        <div class="hero-actions">
          <button class="btn btn-primary" @click="router.push('/profile')">开始建档</button>
        </div>
      </section>
      <section class="flow">
        <h2 class="section-title">四步闭环</h2>
        <div class="flow-grid">
          <div class="flow-step" @click="router.push('/profile')">
            <span class="step-num">01</span><h3 class="step-title">建档</h3>
            <p class="step-desc">录入身体数据、目标和饮食偏好</p>
          </div>
          <div class="flow-step" @click="router.push('/plan')">
            <span class="step-num">02</span><h3 class="step-title">生成计划</h3>
            <p class="step-desc">AI 计算热量缺口，生成饮食和运动方案</p>
          </div>
          <div class="flow-step" @click="router.push('/daily')">
            <span class="step-num">03</span><h3 class="step-title">日常执行</h3>
            <p class="step-desc">打卡、记录餐食、分析动作</p>
          </div>
          <div class="flow-step" @click="router.push('/history')">
            <span class="step-num">04</span><h3 class="step-title">打卡复盘</h3>
            <p class="step-desc">AI 分析执行情况并调整方案</p>
          </div>
        </div>
      </section>
    </template>

    <!-- Loading -->
    <div v-if="loading" class="skeleton-page">
      <div class="skeleton skeleton-hero"></div>
      <div class="skeleton-grid">
        <div class="skeleton skeleton-card" v-for="i in 4" :key="i"></div>
      </div>
    </div>

    <!-- 已建档：引导式 Dashboard -->
    <template v-if="!loading && hasProfile && data">
      <!-- 简要概览 -->
      <section class="dash-overview">
        <div class="overview-left">
          <h1>{{ goalLabel }}计划</h1>
          <p class="overview-sub">{{ data.profile.weight }}kg → {{ data.profile.target_weight }}kg</p>
        </div>
        <div class="overview-right">
          <span class="overview-cal" ref="consumedRef">{{ data.meal_summary.consumed_kcal }}</span>
          <span class="overview-cal-unit">/ {{ data.meal_summary.target_kcal }} kcal</span>
        </div>
      </section>

      <!-- 热量进度条 -->
      <section class="calorie-bar">
        <div class="progress-track">
          <div class="progress-fill" ref="progressRef" :style="{ width: '0%', backgroundColor: calorieStatus.color }"></div>
        </div>
        <span class="calorie-status-text" :style="{ color: calorieStatus.color }">{{ calorieStatus.label }}</span>
      </section>

      <!-- 步骤引导：你接下来该做的 -->
      <section class="steps-section">
        <h2 class="section-title">你接下来该做的</h2>
        <div class="steps-list">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="step-row"
            :class="{ 'step-row--done': step.done, 'step-row--locked': step.locked }"
            @click="!step.locked && router.push(step.route)"
          >
            <span class="step-icon">{{ step.icon }}</span>
            <span class="step-label">{{ step.label }}</span>
            <span class="step-action" v-if="step.action">{{ step.action }}</span>
            <span class="step-arrow" v-if="!step.done && !step.locked">›</span>
          </div>
        </div>
      </section>

      <!-- 数据卡片 -->
      <section class="stats-grid">
        <div class="stat-card" @click="router.push('/checkin')">
          <div class="stat-icon">🔥</div>
          <div class="stat-body">
            <span class="stat-value"><span ref="streakRef">0</span><small>天</small></span>
            <span class="stat-label">连续打卡</span>
          </div>
          <span class="stat-badge" v-if="data.checkin_summary.today_checked">今日已打卡</span>
          <span class="stat-badge stat-badge--warn" v-else>未打卡</span>
        </div>
        <div class="stat-card" @click="router.push('/analysis')">
          <div class="stat-icon">⚕️</div>
          <div class="stat-body">
            <span class="stat-value"><span ref="weightRef">0</span><small>kg</small></span>
            <span class="stat-label">目标 {{ data.profile.target_weight }}kg（差 {{ weightDiff }}kg）</span>
          </div>
        </div>
      </section>

      <!-- 日常工具入口 -->
      <section class="tools-section">
        <h2 class="section-title">日常工具</h2>
        <div class="tools-row">
          <div class="tool-mini" @click="router.push('/meal')">🍽 记录餐食</div>
          <div class="tool-mini" @click="router.push('/food')">🥗 食材识别</div>
          <div class="tool-mini" @click="router.push('/pose')">🏋 动作分析</div>
          <div class="tool-mini" @click="router.push('/body-photo')">📸 身材追踪</div>
        </div>
        <button class="btn btn-ghost btn--sm" @click="router.push('/daily')">查看全部 →</button>
      </section>

      <!-- 计划摘要 -->
      <section v-if="data.latest_plan" class="plan-summary">
        <h2 class="section-title">最新计划摘要</h2>
        <div class="summary-card">
          <p>{{ data.latest_plan.summary }}</p>
          <button class="btn btn-sm btn-ghost" @click="router.push('/plan')">查看完整计划</button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.home { max-width: 800px; margin: 0 auto; }

.load-error { text-align: center; padding: var(--space-10) var(--space-6); }
.load-error-title { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); margin-bottom: var(--space-3); }
.load-error-desc { font-size: var(--text-md); color: var(--color-text-secondary); margin-bottom: var(--space-6); }

/* Hero */
.hero { text-align: center; padding: var(--space-10) 0 var(--space-6); }
.hero-eyebrow { font-size: var(--text-sm); color: var(--color-accent); font-weight: 600; margin-bottom: var(--space-3); }
.hero-title { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); line-height: 1.3; margin-bottom: var(--space-4); }
.hero-sub { font-size: var(--text-md); color: var(--color-text-secondary); line-height: var(--leading-relaxed); margin-bottom: var(--space-6); }
.hero-actions { display: flex; justify-content: center; }

/* Flow steps */
.flow { margin-bottom: var(--space-8); }
.section-title { font-size: var(--text-md); font-weight: 700; color: var(--color-text-primary); margin-bottom: var(--space-3); }
.flow-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); }
.flow-step { padding: var(--space-4); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out); }
.flow-step:hover { border-color: var(--color-accent); }
.step-num { font-family: var(--font-mono); font-size: var(--text-sm); font-weight: 700; color: var(--color-accent); }
.step-title { font-size: var(--text-base); font-weight: 700; margin: var(--space-1) 0; }
.step-desc { font-size: var(--text-sm); color: var(--color-text-tertiary); }

/* Overview */
.dash-overview { display: flex; align-items: flex-start; justify-content: space-between; padding: var(--space-4) 0 var(--space-3); }
.overview-left h1 { font-size: var(--text-xl); font-weight: 800; color: var(--color-text-primary); }
.overview-sub { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.overview-right { text-align: right; }
.overview-cal { font-family: var(--font-mono); font-size: var(--text-xl); font-weight: 800; color: var(--color-text-primary); }
.overview-cal-unit { display: block; font-size: var(--text-xs); color: var(--color-text-tertiary); }

/* Calorie bar */
.calorie-bar { display: flex; align-items: center; gap: var(--space-3); margin-bottom: var(--space-6); }
.progress-track { flex: 1; height: 6px; background: var(--color-border-subtle); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 3px; transition: width 1s var(--ease-out); }
.calorie-status-text { font-size: var(--text-sm); font-weight: 600; flex-shrink: 0; }

/* Steps guide */
.steps-section { margin-bottom: var(--space-6); }
.steps-list { display: flex; flex-direction: column; gap: var(--space-2); }
.step-row { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.step-row:hover:not(.step-row--locked) { border-color: var(--color-accent); background: var(--color-accent-subtle); }
.step-row--done { opacity: 0.6; }
.step-row--locked { cursor: not-allowed; opacity: 0.5; }
.step-icon { font-size: var(--text-base); width: 20px; text-align: center; }
.step-label { flex: 1; font-size: var(--text-sm); font-weight: 500; color: var(--color-text-primary); }
.step-action { font-size: var(--text-xs); color: var(--color-accent); font-weight: 600; }
.step-arrow { font-size: 18px; color: var(--color-text-tertiary); }

/* Stats */
.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); margin-bottom: var(--space-6); }
.stat-card { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-4); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out); }
.stat-card:hover { border-color: var(--color-accent); }
.stat-icon { font-size: 24px; }
.stat-body { flex: 1; display: flex; flex-direction: column; }
.stat-value { font-family: var(--font-mono); font-size: var(--text-lg); font-weight: 700; color: var(--color-text-primary); }
.stat-value small { font-size: var(--text-sm); font-weight: 500; color: var(--color-text-secondary); margin-left: 2px; }
.stat-label { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.stat-badge { font-size: var(--text-xs); padding: 2px var(--space-2); background: var(--color-accent-subtle); color: var(--color-accent); border-radius: var(--radius-sm); font-weight: 500; }
.stat-badge--warn { background: oklch(0.95 0.04 80); color: oklch(0.45 0.12 80); }

/* Tools */
.tools-section { margin-bottom: var(--space-6); }
.tools-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-2); margin-bottom: var(--space-3); }
.tool-mini { padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); font-size: var(--text-sm); font-weight: 500; color: var(--color-text-secondary); cursor: pointer; text-align: center; transition: all var(--duration-fast) var(--ease-out); }
.tool-mini:hover { border-color: var(--color-accent); color: var(--color-accent); }

/* Plan summary */
.plan-summary { margin-bottom: var(--space-6); }
.summary-card { padding: var(--space-4); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); }
.summary-card p { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); margin-bottom: var(--space-3); }

/* Skeleton */
.skeleton-page { padding: var(--space-8) 0; }
.skeleton { background: var(--color-border-subtle); border-radius: var(--radius-sm); animation: pulse 1.5s infinite ease-in-out; }
.skeleton-hero { height: 56px; width: 200px; margin: 0 auto var(--space-6); }
.skeleton-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); }
.skeleton-card { height: 72px; border-radius: var(--radius-md); }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* Button */
.btn { display: inline-flex; align-items: center; justify-content: center; height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-base); font-weight: 600; border: none; cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover { background-color: var(--color-accent-hover); }
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn--sm { height: 32px; padding: 0 var(--space-3); font-size: var(--text-sm); }

@media (max-width: 480px) {
  .flow-grid { grid-template-columns: 1fr; }
  .tools-row { grid-template-columns: 1fr; }
  .stats-grid { grid-template-columns: 1fr; }
}
</style>
