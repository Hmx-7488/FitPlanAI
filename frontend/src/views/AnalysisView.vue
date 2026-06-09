<script setup lang="ts">
import { ref, onMounted, computed, nextTick, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getProfile } from '../api'
import { analyzeProfile } from '../utils/calc'
import type { UserProfileResponse } from '../types'
import type { AnalysisResult } from '../utils/calc'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(true)
const profile = ref<UserProfileResponse | null>(null)
const analysis = ref<AnalysisResult | null>(null)
const pageRef = useTemplateRef<HTMLElement>('pageRef')

const bmiBarPercent = computed(() => {
  if (!analysis.value) return 0
  const bmi = analysis.value.bmi
  if (bmi < 18.5) return (bmi / 18.5) * 25
  if (bmi < 24) return 25 + ((bmi - 18.5) / 5.5) * 25
  if (bmi < 28) return 50 + ((bmi - 24) / 4) * 25
  return 75 + Math.min(((bmi - 28) / 7) * 25, 25)
})

const bmiBarColor = computed(() => {
  if (!analysis.value) return 'var(--color-accent)'
  const cat = analysis.value.bmiCategory
  if (cat === '偏瘦') return 'oklch(0.60 0.12 250)'
  if (cat === '正常') return 'var(--color-accent)'
  if (cat === '偏胖') return 'var(--color-warning)'
  return 'var(--color-danger)'
})

onMounted(async () => {
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }
  try {
    profile.value = await getProfile(Number(userId))
    analysis.value = analyzeProfile(profile.value)
  } catch {
    ElMessage.error('获取档案失败')
    router.push('/profile')
  } finally {
    loading.value = false
    await nextTick()
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.page-header'), { y: 20, opacity: 0, duration: 0.5 })
    tl.from(pageRef.value.querySelectorAll('.bmi-card'), { y: 30, opacity: 0, scale: 0.97, duration: 0.6 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.data-item'), { y: 25, opacity: 0, stagger: 0.1, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.macro-item'), { y: 20, opacity: 0, scale: 0.9, stagger: 0.08, duration: 0.4 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.forecast-card'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.section--pref'), { y: 20, opacity: 0, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.actions'), { y: 15, opacity: 0, duration: 0.3 }, '-=0.1')
    // BMI 条动画
    const bmiFill = pageRef.value.querySelector('.bmi-bar-fill') as HTMLElement
    if (bmiFill) {
      const targetWidth = bmiFill.style.width
      gsap.fromTo(bmiFill, { width: '0%' }, { width: targetWidth, duration: 1.2, ease: 'power2.out', delay: 0.6 })
    }
    // 数字滚动
    const numEls = pageRef.value.querySelectorAll('.data-value, .macro-value, .bmi-number, .forecast-value')
    numEls.forEach(el => {
      const target = parseFloat(el.textContent?.replace(/[^0-9.]/g, '') || '0')
      if (target > 0) {
        const obj = { val: 0 }
        gsap.to(obj, {
          val: target,
          duration: 1,
          ease: 'power2.out',
          delay: 0.4,
          onUpdate() {
            el.childNodes[0].textContent = Math.round(obj.val).toLocaleString()
          },
        })
      }
    })
  }
})
</script>

<template>
  <div class="analysis-page" ref="pageRef">
    <!-- Loading skeleton -->
    <div v-if="loading" class="skeleton-analysis">
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-block" v-for="i in 3" :key="i"></div>
    </div>

    <template v-if="profile && analysis && !loading">
      <!-- Header -->
      <div class="page-header">
        <h1>你的身体画像</h1>
        <p class="header-sub">
          {{ profile.gender === 'male' ? '男' : '女' }} / {{ profile.age }}岁 / {{ profile.height }}cm / {{ profile.weight }}kg
          → 目标 {{ profile.target_weight }}kg
        </p>
      </div>

      <!-- BMI -->
      <section class="section">
        <div class="section-label">体重评估</div>
        <div class="bmi-card">
          <div class="bmi-number">{{ analysis.bmi }}</div>
          <div class="bmi-meta">
            <span class="bmi-category" :style="{ color: bmiBarColor }">{{ analysis.bmiCategory }}</span>
            <span class="bmi-desc">BMI 指数</span>
          </div>
          <div class="bmi-bar-track">
            <div
              class="bmi-bar-fill"
              :style="{ width: bmiBarPercent + '%', backgroundColor: bmiBarColor }"
            ></div>
            <div class="bmi-bar-labels">
              <span>偏瘦</span><span>正常</span><span>偏胖</span><span>肥胖</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 核心数据 -->
      <section class="section">
        <div class="section-label">能量代谢</div>
        <div class="data-grid">
          <div class="data-item">
            <span class="data-value">{{ analysis.bmr }}</span>
            <span class="data-unit">kcal</span>
            <span class="data-label">基础代谢率</span>
            <span class="data-hint">躺着不动也会消耗的热量</span>
          </div>
          <div class="data-item">
            <span class="data-value">{{ analysis.tdee }}</span>
            <span class="data-unit">kcal</span>
            <span class="data-label">每日总消耗</span>
            <span class="data-hint">含 {{ analysis.activityLabel }} 活动的消耗</span>
          </div>
          <div class="data-item data-item--accent">
            <span class="data-value">{{ analysis.targetCalories }}</span>
            <span class="data-unit">kcal</span>
            <span class="data-label">建议摄入</span>
            <span class="data-hint">{{ profile.goal_type === 'muscle_gain' ? '每天增加 ' + analysis.deficit + ' kcal 热量盈余' : '每天减少 ' + analysis.deficit + ' kcal 热量缺口' }}</span>
          </div>
        </div>
      </section>

      <!-- 营养素 -->
      <section class="section">
        <div class="section-label">每日营养目标</div>
        <div class="macro-grid">
          <div class="macro-item">
            <span class="macro-value">{{ analysis.proteinG }}<small>g</small></span>
            <span class="macro-label">蛋白质</span>
          </div>
          <div class="macro-item">
            <span class="macro-value">{{ analysis.carbsG }}<small>g</small></span>
            <span class="macro-label">碳水</span>
          </div>
          <div class="macro-item">
            <span class="macro-value">{{ analysis.fatG }}<small>g</small></span>
            <span class="macro-label">脂肪</span>
          </div>
          <div class="macro-item macro-item--subtle">
            <span class="macro-value">{{ analysis.waterMl }}<small>ml</small></span>
            <span class="macro-label">饮水</span>
          </div>
        </div>
      </section>

      <!-- 目标预测 -->
      <section class="section">
        <div class="section-label">{{ profile.goal_type === 'muscle_gain' ? '增重预测' : '减重预测' }}</div>
        <div class="forecast-card">
          <div class="forecast-main">
            <span class="forecast-value">{{ Math.abs(analysis.weightToLose) }}</span>
            <span class="forecast-unit">kg {{ profile.goal_type === 'muscle_gain' ? '待增' : '待减' }}</span>
          </div>
          <div class="forecast-meta">
            <span v-if="profile.goal_type === 'muscle_gain'">
              <span v-if="analysis.weightToLose < 0">
                按安全速度（每周 0.3-0.5kg），预计 <strong>{{ Math.ceil(Math.abs(analysis.weightToLose) / 0.4) }}</strong> 周达成目标
              </span>
              <span v-else>当前体重已达到或超过目标</span>
            </span>
            <span v-else>
              <span v-if="analysis.estimatedWeeks > 0">
                按安全速度（每周 0.7kg），预计 <strong>{{ analysis.estimatedWeeks }}</strong> 周达成目标
              </span>
              <span v-else>当前体重已低于目标，无需减重</span>
            </span>
          </div>
        </div>
      </section>

      <!-- 偏好确认 -->
      <section class="section section--pref">
        <div class="pref-row">
          <span class="pref-label">活动水平</span>
          <span class="pref-value">{{ analysis.activityLabel }}</span>
        </div>
        <div class="pref-row">
          <span class="pref-label">饮食偏好</span>
          <span class="pref-value">{{ analysis.dietLabel }}</span>
        </div>
        <div class="pref-row">
          <span class="pref-label">训练目标</span>
          <span class="pref-value">{{ profile.goal_type === 'muscle_gain' ? '增肌' : '减脂' }}</span>
        </div>
        <div class="pref-row" v-if="profile.body_fat_rate">
          <span class="pref-label">体脂率</span>
          <span class="pref-value">{{ profile.body_fat_rate }}%</span>
        </div>
        <div class="pref-row" v-if="profile.forbidden_foods.length">
          <span class="pref-label">忌口食物</span>
          <span class="pref-value">{{ profile.forbidden_foods.join('、') }}</span>
        </div>
        <div class="pref-row" v-if="profile.injuries.length">
          <span class="pref-label">伤病部位</span>
          <span class="pref-value pref-value--warn">{{ profile.injuries.join('、') }}</span>
        </div>
        <div class="pref-row" v-if="profile.allergies.length">
          <span class="pref-label">过敏食材</span>
          <span class="pref-value pref-value--danger">{{ profile.allergies.join('、') }}</span>
        </div>
      </section>

      <!-- Actions -->
      <div class="actions">
        <button class="btn btn-primary" @click="router.push('/plan')">生成完整计划</button>
        <button class="btn btn-ghost" @click="router.push('/profile')">修改数据</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.analysis-page {
  max-width: 640px;
  margin: 0 auto;
}

/* Skeleton */
.skeleton-analysis {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  padding: var(--space-8) 0;
}
.skeleton-title { width: 200px; height: 32px; }
.skeleton-block { width: 100%; height: 120px; }

/* Header */
.page-header {
  margin-bottom: var(--space-8);
}
.page-header h1 {
  font-size: var(--text-2xl);
  font-weight: 800;
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
  margin-bottom: var(--space-2);
}
.header-sub {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  font-family: var(--font-mono);
}

/* Section */
.section {
  margin-bottom: var(--space-6);
}
.section-label {
  font-size: var(--text-sm);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border-subtle);
}

/* BMI */
.bmi-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.bmi-number {
  font-family: var(--font-mono);
  font-size: 40px;
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1;
}
.bmi-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.bmi-category {
  font-size: var(--text-lg);
  font-weight: 700;
}
.bmi-desc {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.bmi-bar-track {
  width: 100%;
  margin-top: var(--space-3);
}
.bmi-bar-fill {
  height: 6px;
  border-radius: 3px;
  transition: width var(--duration-normal) var(--ease-out);
}
.bmi-bar-labels {
  display: flex;
  justify-content: space-between;
  margin-top: var(--space-1);
  font-size: 11px;
  color: var(--color-text-tertiary);
}

/* Data grid */
.data-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
}
.data-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
}
.data-item--accent {
  background: var(--color-accent-subtle);
  border-color: oklch(0.90 0.03 145);
}
.data-value {
  font-family: var(--font-mono);
  font-size: var(--text-xl);
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1;
}
.data-unit {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-tertiary);
  margin-top: 2px;
}
.data-label {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  margin-top: var(--space-2);
}
.data-hint {
  font-size: 11px;
  color: var(--color-text-tertiary);
  line-height: var(--leading-normal);
  margin-top: 2px;
}

/* Macros */
.macro-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
}
.macro-item {
  background: var(--color-accent-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  text-align: center;
}
.macro-item--subtle {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
}
.macro-value {
  font-family: var(--font-mono);
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--color-text-primary);
}
.macro-value small {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-left: 1px;
}
.macro-label {
  display: block;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-tertiary);
  margin-top: var(--space-1);
}

/* Forecast */
.forecast-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-5);
}
.forecast-main {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-shrink: 0;
}
.forecast-value {
  font-family: var(--font-mono);
  font-size: 32px;
  font-weight: 800;
  color: var(--color-text-primary);
}
.forecast-unit {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
.forecast-meta {
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  line-height: var(--leading-normal);
}
.forecast-meta strong {
  color: var(--color-accent);
  font-weight: 700;
}

/* Preferences */
.section--pref {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
}
.pref-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) 0;
}
.pref-row + .pref-row {
  border-top: 1px solid var(--color-border-subtle);
}
.pref-label {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}
.pref-value {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
}

.pref-value--warn {
  color: var(--color-warning);
}

.pref-value--danger {
  color: oklch(0.55 0.18 25);
}

/* Actions */
.actions {
  display: flex;
  gap: var(--space-3);
  padding-top: var(--space-6);
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 44px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-weight: 600;
  font-family: var(--font-family);
  border: none;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.btn-primary {
  background-color: var(--color-accent);
  color: white;
}
.btn-primary:hover {
  background-color: var(--color-accent-hover);
}
.btn-ghost {
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}
.btn-ghost:hover {
  border-color: var(--color-text-tertiary);
}

@media (max-width: 480px) {
  .data-grid {
    grid-template-columns: 1fr;
  }
  .macro-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .forecast-card {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-3);
  }
}
</style>
