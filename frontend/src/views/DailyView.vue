<script setup lang="ts">
import { ref, onMounted, computed, nextTick, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'
import { getDashboard, type DashboardData } from '../api'
import { progressFillIn, countUp } from '../utils/animations'

const router = useRouter()
const loading = ref(true)
const data = ref<DashboardData | null>(null)
const loadError = ref(false)
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const consumedRef = useTemplateRef<HTMLElement>('consumedRef')

const calorieStatus = computed(() => {
  if (!data.value) return { label: '未知', color: 'var(--color-text-tertiary)' }
  const pct = data.value.meal_summary.progress_pct
  if (pct < 30) return { label: '刚开始', color: 'var(--color-accent)' }
  if (pct < 80) return { label: '进行中', color: 'var(--color-accent)' }
  if (pct < 100) return { label: '接近目标', color: 'var(--color-warning)' }
  return { label: '已达标', color: 'oklch(0.55 0.18 25)' }
})

const tools = [
  { icon: '\uD83C\uDF5D', title: '记录餐食', desc: '拍照识别热量', route: '/meal' },
  { icon: '\uD83E\uDD57', title: '食材识别', desc: '拍照生成菜谱', route: '/food' },
  { icon: '\uD83C\uDFCB\uFE0F', title: '动作分析', desc: 'AI 评估动作', route: '/pose' },
  { icon: '\uD83D\uDCF7', title: '身材追踪', desc: '照片估算体脂', route: '/body-photo' },
  { icon: '\uD83D\uDC69\u200D\u2695\uFE0F', title: '身体画像', desc: 'BMI/BMR/营养目标', route: '/analysis' },
  { icon: '\uD83D\uDCD2', title: '修改档案', desc: '更新身体数据', route: '/profile' },
]

async function loadData() {
  const userId = localStorage.getItem('userId')
  if (!userId) { loading.value = false; return }
  loading.value = true
  loadError.value = false
  try {
    data.value = await getDashboard(Number(userId))
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
    await nextTick()
    if (pageRef.value && data.value && consumedRef.value) {
      countUp(consumedRef.value, data.value.meal_summary.consumed_kcal)
      const bar = pageRef.value.querySelector('.progress-fill') as HTMLElement
      if (bar) progressFillIn(bar, data.value.meal_summary.progress_pct)
    }
  }
}

onMounted(loadData)
</script>

<template>
  <div class="daily-page" ref="pageRef">
    <div class="page-header">
      <h1>日常工具</h1>
      <p>打卡、记录餐食、分析动作——日常使用的一切都在这里。</p>
    </div>

    <div v-if="loading" class="loading-hint">加载中...</div>
    <div v-else-if="loadError" class="loading-hint">
      数据加载失败，<button class="link-btn" @click="loadData">重试</button>
    </div>

    <template v-else>
      <!-- 今日热量概览（如果已建档） -->
      <section v-if="data" class="calorie-overview">
        <div class="calorie-top">
          <span class="calorie-consumed" ref="consumedRef">{{ data.meal_summary.consumed_kcal }}</span>
          <span class="calorie-unit">/ {{ data.meal_summary.target_kcal }} kcal</span>
          <span class="calorie-status" :style="{ color: calorieStatus.color }">{{ calorieStatus.label }}</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: '0%', backgroundColor: calorieStatus.color }"></div>
        </div>
        <div class="calorie-detail">
          <span>剩余 {{ data.meal_summary.remaining_kcal }} kcal</span>
          <span>今日 {{ data.meal_summary.meal_count }} 餐</span>
        </div>
      </section>

      <!-- 今日打卡快捷入口 -->
      <section v-if="data" class="checkin-quick">
        <div class="checkin-card" @click="router.push('/checkin')">
          <span class="checkin-icon">\uD83D\uDD25</span>
          <div class="checkin-body">
            <span class="checkin-title">{{ data.checkin_summary.today_checked ? '今日已打卡' : '今日未打卡' }}</span>
            <span class="checkin-sub">连续 {{ data.checkin_summary.streak }} 天</span>
          </div>
          <span class="checkin-arrow">\u203A</span>
        </div>
      </section>

      <!-- 工具网格 -->
      <section class="tools-section">
        <h2 class="section-title">工具</h2>
        <div class="tools-grid">
          <div
            v-for="tool in tools"
            :key="tool.route"
            class="tool-card"
            @click="router.push(tool.route)"
          >
            <span class="tool-icon">{{ tool.icon }}</span>
            <div class="tool-body">
              <span class="tool-title">{{ tool.title }}</span>
              <span class="tool-desc">{{ tool.desc }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 复盘入口 -->
      <section v-if="data && data.checkin_summary.total_days >= 3" class="review-quick">
        <div class="review-card" @click="router.push('/history')">
          <span class="review-icon">\uD83E\uDDE0</span>
          <div class="review-body">
            <span class="review-title">查看 AI 复盘</span>
            <span class="review-sub">已打卡 {{ data.checkin_summary.total_days }} 天，可以生成复盘了</span>
          </div>
          <span class="review-arrow">\u203A</span>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.daily-page { max-width: 800px; margin: 0 auto; }

.page-header { margin-bottom: var(--space-6); }
.page-header h1 { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); margin-bottom: var(--space-1); }
.page-header p { font-size: var(--text-md); color: var(--color-text-secondary); }

.loading-hint { text-align: center; padding: var(--space-8); color: var(--color-text-tertiary); }
.link-btn { background: none; border: none; color: var(--color-accent); cursor: pointer; font-size: inherit; text-decoration: underline; }

/* Calorie overview */
.calorie-overview {
  background: var(--color-accent-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  margin-bottom: var(--space-5);
}
.calorie-top { display: flex; align-items: baseline; gap: var(--space-2); margin-bottom: var(--space-3); }
.calorie-consumed { font-family: var(--font-mono); font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); }
.calorie-unit { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.calorie-status { font-size: var(--text-sm); font-weight: 600; margin-left: auto; }
.progress-track { height: 6px; background: var(--color-border-subtle); border-radius: 3px; overflow: hidden; margin-bottom: var(--space-2); }
.progress-fill { height: 100%; border-radius: 3px; transition: width 1s var(--ease-out); }
.calorie-detail { display: flex; justify-content: space-between; font-size: var(--text-sm); color: var(--color-text-secondary); }

/* Checkin quick */
.checkin-quick { margin-bottom: var(--space-6); }
.checkin-card {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-4); border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md); background: var(--color-surface); cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
}
.checkin-card:hover { border-color: var(--color-accent); }
.checkin-icon { font-size: 28px; }
.checkin-body { flex: 1; display: flex; flex-direction: column; }
.checkin-title { font-size: var(--text-base); font-weight: 600; color: var(--color-text-primary); }
.checkin-sub { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.checkin-arrow { font-size: 20px; color: var(--color-text-tertiary); }

/* Tools grid */
.tools-section { margin-bottom: var(--space-6); }
.section-title { font-size: var(--text-md); font-weight: 700; color: var(--color-text-primary); margin-bottom: var(--space-3); }
.tools-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); }
.tool-card {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-4); border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md); background: var(--color-surface); cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.tool-card:hover { border-color: var(--color-accent); background: var(--color-accent-subtle); }
.tool-icon { font-size: 28px; flex-shrink: 0; }
.tool-body { display: flex; flex-direction: column; min-width: 0; }
.tool-title { font-size: var(--text-sm); font-weight: 600; color: var(--color-text-primary); }
.tool-desc { font-size: var(--text-xs); color: var(--color-text-tertiary); }

/* Review quick */
.review-quick { margin-bottom: var(--space-6); }
.review-card {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-4); border: 1px solid var(--color-accent);
  border-radius: var(--radius-md); background: var(--color-accent-subtle); cursor: pointer;
}
.review-icon { font-size: 28px; }
.review-body { flex: 1; display: flex; flex-direction: column; }
.review-title { font-size: var(--text-base); font-weight: 600; color: var(--color-accent); }
.review-sub { font-size: var(--text-sm); color: var(--color-text-secondary); }
.review-arrow { font-size: 20px; color: var(--color-accent); }

@media (max-width: 480px) {
  .tools-grid { grid-template-columns: 1fr; }
}
</style>
