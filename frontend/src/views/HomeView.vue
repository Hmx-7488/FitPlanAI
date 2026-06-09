<script setup lang="ts">
import { ref, onMounted, computed, nextTick, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'
import { getDashboard, type DashboardData } from '../api'
import { heroEntrance, dashboardEntrance, flowStepsEntrance, progressFillIn, countUp } from '../utils/animations'

const router = useRouter()
const loading = ref(true)
const data = ref<DashboardData | null>(null)
const hasProfile = ref(false)
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

const quickActions = [
  { icon: '&#128202;', title: '身体画像', desc: '查看 BMI、BMR、营养目标', route: '/analysis' },
  { icon: '&#128203;', title: '训练计划', desc: 'AI 生成一周计划', route: '/plan' },
  { icon: '&#127859;', title: '食材识别', desc: '拍照识别食材生成菜谱', route: '/food' },
  { icon: '&#127860;', title: '记录餐食', desc: '拍照识别热量', route: '/meal' },
  { icon: '&#127947;', title: '动作分析', desc: 'AI 评估训练动作', route: '/pose' },
  { icon: '&#128247;', title: '身材分析', desc: '照片估算体脂率', route: '/body-photo' },
]

onMounted(async () => {
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
  try {
    data.value = await getDashboard(Number(userId))
    hasProfile.value = true
  } catch {
    hasProfile.value = false
  } finally {
    loading.value = false
    await nextTick()
    if (!pageRef.value) return
    if (hasProfile.value && data.value) {
      dashboardEntrance(pageRef.value)
      // 数字滚动
      if (consumedRef.value) countUp(consumedRef.value, data.value.meal_summary.consumed_kcal)
      if (streakRef.value) countUp(streakRef.value, data.value.checkin_summary.streak, { suffix: '' })
      if (weightRef.value) countUp(weightRef.value, data.value.checkin_summary.latest_weight, { suffix: '', duration: 1 })
      // 进度条
      if (progressRef.value) progressFillIn(progressRef.value, data.value.meal_summary.progress_pct)
    } else {
      heroEntrance(pageRef.value)
      flowStepsEntrance(pageRef.value)
    }
  }
})
</script>

<template>
  <div class="home" ref="pageRef">
    <!-- 未建档：引导页 -->
    <template v-if="!loading && !hasProfile">
      <section class="hero">
        <p class="hero-eyebrow">基于 Agentic RAG 的智能减脂教练</p>
        <h1 class="hero-title">吃对了，练对了，<br>脂肪自然就掉了。</h1>
        <p class="hero-sub">
          输入身体数据，AI 生成饮食和运动计划。<br>
          每天打卡，自动复盘并调整方案。
        </p>
        <div class="hero-actions">
          <button class="btn btn-primary" @click="router.push('/profile')">开始建档</button>
        </div>
      </section>

      <section class="flow">
        <h2 class="section-title">四步闭环</h2>
        <div class="flow-grid">
          <div class="flow-step" @click="router.push('/profile')">
            <span class="step-num">01</span>
            <h3 class="step-title">建档</h3>
            <p class="step-desc">录入身体数据、目标和饮食偏好</p>
          </div>
          <div class="flow-step" @click="router.push('/plan')">
            <span class="step-num">02</span>
            <h3 class="step-title">生成计划</h3>
            <p class="step-desc">AI 计算热量缺口，生成饮食和运动方案</p>
          </div>
          <div class="flow-step" @click="router.push('/food')">
            <span class="step-num">03</span>
            <h3 class="step-title">食材识别</h3>
            <p class="step-desc">拍照识别食材，生成轻食菜谱</p>
          </div>
          <div class="flow-step" @click="router.push('/checkin')">
            <span class="step-num">04</span>
            <h3 class="step-title">打卡复盘</h3>
            <p class="step-desc">记录饮食运动，AI 分析调整</p>
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

    <!-- 已建档：Dashboard -->
    <template v-if="!loading && hasProfile && data">
      <!-- Header -->
      <section class="dash-header">
        <div class="dash-greeting">
          <h1>今日 Dashboard</h1>
          <p class="dash-sub">
            {{ data.profile.gender === 'male' ? '男' : '女' }} / {{ data.profile.age }}岁
            / {{ data.profile.height }}cm / {{ data.profile.weight }}kg
            <span class="goal-badge" :class="data.profile.goal_type">{{ goalLabel }}</span>
          </p>
        </div>
      </section>

      <!-- 热量进度 -->
      <section class="calorie-card">
        <div class="calorie-top">
          <div class="calorie-main">
            <span class="calorie-consumed" ref="consumedRef">{{ data.meal_summary.consumed_kcal }}</span>
            <span class="calorie-unit">/ {{ data.meal_summary.target_kcal }} kcal</span>
          </div>
          <span class="calorie-status" :style="{ color: calorieStatus.color }">{{ calorieStatus.label }}</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" ref="progressRef" :style="{ width: '0%', backgroundColor: calorieStatus.color }"></div>
        </div>
        <div class="calorie-detail">
          <span>剩余 <strong>{{ data.meal_summary.remaining_kcal }}</strong> kcal</span>
          <span>今日 {{ data.meal_summary.meal_count }} 餐</span>
        </div>
        <div class="macro-row" v-if="data.meal_summary.meal_count > 0">
          <span class="macro-pill">蛋白 {{ data.meal_summary.consumed_protein }}g</span>
          <span class="macro-pill">碳水 {{ data.meal_summary.consumed_carbs }}g</span>
          <span class="macro-pill">脂肪 {{ data.meal_summary.consumed_fat }}g</span>
        </div>
        <div class="calorie-actions">
          <button class="btn btn-sm btn-primary" @click="router.push('/meal')">记录餐食</button>
        </div>
      </section>

      <!-- 数据卡片 -->
      <section class="stats-grid">
        <!-- 打卡状态 -->
        <div class="stat-card" @click="router.push('/checkin')">
          <div class="stat-icon">&#128293;</div>
          <div class="stat-body">
            <span class="stat-value"><span ref="streakRef">0</span><small>天</small></span>
            <span class="stat-label">连续打卡</span>
          </div>
          <span class="stat-badge" v-if="data.checkin_summary.today_checked">今日已打卡</span>
          <span class="stat-badge stat-badge--warn" v-else>未打卡</span>
        </div>

        <!-- 体重 -->
        <div class="stat-card" @click="router.push('/analysis')">
          <div class="stat-icon">&#9878;&#65039;</div>
          <div class="stat-body">
            <span class="stat-value"><span ref="weightRef">0</span><small>kg</small></span>
            <span class="stat-label">目标 {{ data.profile.target_weight }}kg（差 {{ weightDiff }}kg）</span>
          </div>
          <span class="stat-badge" v-if="data.checkin_summary.weight_change !== 0">
            {{ data.checkin_summary.weight_change > 0 ? '+' : '' }}{{ data.checkin_summary.weight_change }}kg
          </span>
        </div>

        <!-- 营养目标 -->
        <div class="stat-card" v-if="data.latest_plan" @click="router.push('/plan')">
          <div class="stat-icon">&#127869;</div>
          <div class="stat-body">
            <span class="stat-value">{{ data.latest_plan.daily_calorie_target }}<small>kcal/天</small></span>
            <span class="stat-label">蛋白 {{ data.latest_plan.protein_g }}g / 碳水 {{ data.latest_plan.carbs_g }}g / 脂肪 {{ data.latest_plan.fat_g }}g</span>
          </div>
          <span class="stat-badge">已生成计划</span>
        </div>
        <div class="stat-card stat-card--empty" v-else @click="router.push('/plan')">
          <div class="stat-icon">&#128203;</div>
          <div class="stat-body">
            <span class="stat-label">尚未生成计划，点击开始</span>
          </div>
        </div>
      </section>

      <!-- 快捷入口 -->
      <section class="quick-section">
        <h2 class="section-title">功能入口</h2>
        <div class="quick-grid">
          <div
            v-for="action in quickActions"
            :key="action.route"
            class="quick-item"
            @click="router.push(action.route)"
          >
            <span class="quick-icon" v-html="action.icon"></span>
            <div class="quick-body">
              <span class="quick-title">{{ action.title }}</span>
              <span class="quick-desc">{{ action.desc }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 计划摘要 -->
      <section class="plan-summary" v-if="data.latest_plan?.summary">
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
.home {
  max-width: 900px;
  margin: 0 auto;
}

/* Skeleton */
.skeleton-page { display: flex; flex-direction: column; gap: var(--space-5); padding: var(--space-4) 0; }
.skeleton { background: var(--color-border-subtle); border-radius: var(--radius-md); animation: pulse 1.5s ease-in-out infinite; }
.skeleton-hero { height: 180px; }
.skeleton-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-4); }
.skeleton-card { height: 100px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

/* Hero (未建档) */
.hero { padding: var(--space-12) 0 var(--space-10); text-align: center; }
.hero-eyebrow { font-size: var(--text-sm); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--color-accent); margin-bottom: var(--space-4); }
.hero-title { font-size: clamp(28px, 5vw, 42px); font-weight: 800; line-height: var(--leading-tight); color: var(--color-text-primary); margin-bottom: var(--space-5); letter-spacing: -0.02em; }
.hero-sub { font-size: var(--text-md); color: var(--color-text-secondary); line-height: var(--leading-relaxed); margin-bottom: var(--space-8); max-width: 480px; margin-left: auto; margin-right: auto; }
.hero-actions { display: flex; justify-content: center; gap: var(--space-3); }

/* Dashboard Header */
.dash-header { margin-bottom: var(--space-6); }
.dash-greeting h1 { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); letter-spacing: -0.02em; margin-bottom: var(--space-2); }
.dash-sub { font-size: var(--text-base); color: var(--color-text-secondary); font-family: var(--font-mono); }
.goal-badge { font-size: var(--text-xs); font-weight: 700; padding: 2px 8px; border-radius: var(--radius-sm); margin-left: var(--space-2); }
.goal-badge.fat_loss { background: oklch(0.93 0.06 145); color: oklch(0.40 0.12 145); }
.goal-badge.muscle_gain { background: oklch(0.93 0.06 250); color: oklch(0.40 0.12 250); }

/* Calorie Card */
.calorie-card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); margin-bottom: var(--space-5); }
.calorie-top { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: var(--space-3); }
.calorie-main { display: flex; align-items: baseline; gap: var(--space-2); }
.calorie-consumed { font-family: var(--font-mono); font-size: 36px; font-weight: 800; color: var(--color-text-primary); line-height: 1; }
.calorie-unit { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.calorie-status { font-size: var(--text-sm); font-weight: 700; }
.progress-track { height: 8px; background: var(--color-border-subtle); border-radius: 4px; overflow: hidden; margin-bottom: var(--space-3); }
.progress-fill { height: 100%; border-radius: 4px; transition: width var(--duration-normal) var(--ease-out); }
.calorie-detail { display: flex; justify-content: space-between; font-size: var(--text-sm); color: var(--color-text-secondary); margin-bottom: var(--space-3); }
.calorie-detail strong { color: var(--color-text-primary); font-weight: 700; font-family: var(--font-mono); }
.macro-row { display: flex; gap: var(--space-2); margin-bottom: var(--space-3); }
.macro-pill { font-size: var(--text-xs); font-family: var(--font-mono); font-weight: 600; padding: 3px 10px; background: var(--color-accent-subtle); color: var(--color-accent); border-radius: var(--radius-sm); }
.calorie-actions { display: flex; }

/* Stats Grid */
.stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-4); margin-bottom: var(--space-6); }
.stat-card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-4); display: flex; flex-direction: column; gap: var(--space-2); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); position: relative; min-width: 0; overflow: hidden; }
.stat-card:hover { border-color: var(--color-accent); transform: translateY(-2px); box-shadow: var(--shadow-md); }
.stat-card--empty { border-style: dashed; opacity: 0.7; }
.stat-card--empty:hover { opacity: 1; }
.stat-icon { font-size: 24px; line-height: 1; }
.stat-body { display: flex; flex-direction: column; min-width: 0; }
.stat-value { font-family: var(--font-mono); font-size: var(--text-xl); font-weight: 800; color: var(--color-text-primary); line-height: 1.2; }
.stat-value small { font-size: var(--text-xs); font-weight: 500; color: var(--color-text-tertiary); margin-left: 2px; }
.stat-label { font-size: var(--text-xs); color: var(--color-text-tertiary); margin-top: var(--space-1); overflow-wrap: anywhere; line-height: var(--leading-normal); }
.stat-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: var(--radius-sm); background: oklch(0.93 0.06 145); color: oklch(0.40 0.12 145); align-self: flex-start; }
.stat-badge--warn { background: oklch(0.93 0.06 80); color: oklch(0.45 0.12 80); }

/* Quick Actions */
.quick-section { margin-bottom: var(--space-6); }
.section-title { font-size: var(--text-lg); font-weight: 700; color: var(--color-text-primary); margin-bottom: var(--space-4); letter-spacing: -0.01em; }
.quick-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); }
.quick-item { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-4); background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); min-width: 0; overflow: hidden; }
.quick-item:hover { border-color: var(--color-accent); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
.quick-icon { font-size: 22px; flex-shrink: 0; }
.quick-body { display: flex; flex-direction: column; min-width: 0; }
.quick-title { font-size: var(--text-sm); font-weight: 700; color: var(--color-text-primary); }
.quick-desc { font-size: var(--text-xs); color: var(--color-text-tertiary); white-space: normal; overflow-wrap: anywhere; line-height: var(--leading-normal); }

/* Plan Summary */
.plan-summary { margin-bottom: var(--space-6); }
.summary-card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.summary-card p { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); margin-bottom: var(--space-4); white-space: pre-line; overflow-wrap: anywhere; }

/* Flow (未建档) */
.flow { padding: var(--space-6) 0; }
.flow-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-4); }
.flow-step { padding: var(--space-5); background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); cursor: pointer; transition: all var(--duration-normal) var(--ease-out); }
.flow-step:hover { border-color: var(--color-accent); transform: translateY(-2px); box-shadow: var(--shadow-md); }
.step-num { font-family: var(--font-mono); font-size: var(--text-xs); font-weight: 700; color: var(--color-accent); display: block; margin-bottom: var(--space-2); }
.step-title { font-size: var(--text-md); font-weight: 700; color: var(--color-text-primary); margin-bottom: var(--space-1); }
.step-desc { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-normal); }

/* Buttons */
.btn { display: inline-flex; align-items: center; justify-content: center; height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-base); font-weight: 600; font-family: var(--font-family); border: none; cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.btn-sm { height: 36px; padding: 0 var(--space-4); font-size: var(--text-sm); }
.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover { background-color: var(--color-accent-hover); transform: translateY(-1px); box-shadow: var(--shadow-md); }
.btn-ghost { background-color: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { color: var(--color-text-primary); border-color: var(--color-text-tertiary); }

/* Responsive */
@media (max-width: 768px) {
  .stats-grid { grid-template-columns: 1fr; }
  .quick-grid { grid-template-columns: repeat(2, 1fr); }
  .flow-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 480px) {
  .quick-grid { grid-template-columns: 1fr; }
  .flow-grid { grid-template-columns: 1fr; }
  .hero-actions { flex-direction: column; align-items: center; }
}
</style>
