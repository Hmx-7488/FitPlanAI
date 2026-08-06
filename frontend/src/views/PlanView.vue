<script setup lang="ts">
import { ref, onMounted, computed, nextTick, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getLatestPlan, generatePlan, getExerciseDetail, type ExerciseDetail } from '../api'
import type { PlanResponse, NeedInfoResponse, StructuredWorkoutPlan } from '../types'
import { sanitizeHtml } from '../utils/sanitize'
import gsap from 'gsap'

const router = useRouter()
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const loading = ref(false)
const initialLoading = ref(true)
const plan = ref<PlanResponse | null>(null)
const followup = ref<NeedInfoResponse | null>(null)
const activeTab = ref('meal')
const loadingSeconds = ref(0)
let loadingTimer: ReturnType<typeof setInterval> | null = null

/** 从 created_at 计算具体日期列表 */
const planDates = computed(() => {
  if (!plan.value?.created_at) return []
  const base = new Date(plan.value.created_at)
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return Array.from({ length: 3 }, (_, i) => {
    const d = new Date(base)
    d.setDate(d.getDate() + i)
    const m = d.getMonth() + 1
    const day = d.getDate()
    const wd = weekdays[d.getDay()]
    return `${m}月${day}日 ${wd}`
  })
})

const progressPercent = computed(() => {
  const s = loadingSeconds.value
  if (s < 5) return 10
  if (s < 15) return 25
  if (s < 30) return 45
  if (s < 60) return 65
  if (s < 90) return 80
  return 90
})

const progressLabel = computed(() => {
  const s = loadingSeconds.value
  if (s < 10) return '正在检索营养知识...'
  if (s < 30) return '正在计算营养目标...'
  if (s < 60) return '正在生成饮食计划...'
  if (s < 90) return '正在生成运动计划...'
  return '正在生成执行建议...'
})

const waitMessage = computed(() => {
  const s = loadingSeconds.value
  if (s < 15) return 'AI 教练正在为你量身定制计划，大约需要 2 分钟。趁这个时间站起来活动一下吧。'
  if (s < 45) return '正在根据你的身体数据生成饮食方案，耐心等一下。'
  if (s < 75) return '饮食方案完成，正在生成运动计划...'
  return '快好了，最后一步...'
})

/** 加载已有计划（不触发生成） */
async function loadExistingPlan() {
  const userId = localStorage.getItem('userId')
  if (!userId) return false
  try {
    const existing = await getLatestPlan(Number(userId))
    if (existing) {
      plan.value = existing
      return true
    }
  } catch { /* ignore */ }
  return false
}

/** 生成新计划 */
async function fetchPlan() {
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  loading.value = true
  followup.value = null
  loadingSeconds.value = 0
  loadingTimer = setInterval(() => { loadingSeconds.value++ }, 1000)

  try {
    const result = await generatePlan(Number(userId))
    plan.value = result
    followup.value = null
    ElMessage.success('计划生成成功')
  } catch (err: any) {
    // Agent 判断信息不完整，返回追问
    if (err.response?.status === 422 && err.response?.data?.status === 'need_info') {
      followup.value = err.response.data as NeedInfoResponse
      ElMessage.warning('信息不完整，请补充后再生成')
    } else {
      ElMessage.error(err.response?.data?.detail || '生成计划失败，请稍后重试')
    }
  } finally {
    loading.value = false
    if (loadingTimer) { clearInterval(loadingTimer); loadingTimer = null }
  }
}

/** 在 meal_plan 文本中替换"第X天"为具体日期 */
function replaceDayLabels(text: string): string {
  if (!planDates.value.length) return text
  return text
    .replace(/第1天|第一天/g, planDates.value[0])
    .replace(/第2天|第二天/g, planDates.value[1])
    .replace(/第3天|第三天/g, planDates.value[2])
}

function formatPlan(text: string): string {
  const rendered = replaceDayLabels(text)
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/#{1,3}\s(.+)/g, '<h4>$1</h4>')
  return sanitizeHtml(rendered)
}

/** 解析结构化训练计划 JSON */
const structuredWorkout = computed<StructuredWorkoutPlan | null>(() => {
  if (!plan.value?.workout_plan_json) return null
  try {
    return JSON.parse(plan.value.workout_plan_json) as StructuredWorkoutPlan
  } catch {
    return null
  }
})

/** 动作详情缓存：exercise_id -> ExerciseDetail */
const exerciseCache = ref<Record<string, ExerciseDetail>>({})
const expandedExercises = ref<Set<string>>(new Set())
const loadingExercises = ref<Set<string>>(new Set())

async function toggleExercise(exerciseId: string) {
  if (expandedExercises.value.has(exerciseId)) {
    expandedExercises.value.delete(exerciseId)
    return
  }
  expandedExercises.value.add(exerciseId)

  // 懒加载动作详情
  if (!exerciseCache.value[exerciseId] && exerciseId !== 'manual' && !loadingExercises.value.has(exerciseId)) {
    loadingExercises.value.add(exerciseId)
    try {
      const detail = await getExerciseDetail(exerciseId)
      exerciseCache.value[exerciseId] = detail
    } catch {
      // 加载失败静默处理，卡片仍显示基本信息
    } finally {
      loadingExercises.value.delete(exerciseId)
    }
  }
}

function animatePlan() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.hero-metric'), { y: 30, opacity: 0, scale: 0.95, duration: 0.6 })
    tl.from(pageRef.value.querySelectorAll('.macro-item'), { y: 20, opacity: 0, scale: 0.9, stagger: 0.08, duration: 0.4 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.tabs'), { y: 15, opacity: 0, duration: 0.4 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.plan-content'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.summary-section'), { y: 20, opacity: 0, duration: 0.5 }, '-=0.2')
    // 数字滚动
    const metricEl = pageRef.value.querySelector('.metric-value') as HTMLElement
    if (metricEl) {
      const target = parseInt(metricEl.textContent || '0')
      const obj = { val: 0 }
      gsap.to(obj, { val: target, duration: 1.2, ease: 'power2.out', delay: 0.2, onUpdate() { metricEl.textContent = Math.round(obj.val).toLocaleString() } })
    }
  })
}

watch(() => plan.value, (val) => { if (val) animatePlan() })

onMounted(async () => {
  const userId = localStorage.getItem('userId')
  if (!userId) { initialLoading.value = false; return }
  await loadExistingPlan()
  initialLoading.value = false
  if (plan.value) animatePlan()
})
</script>

<template>
  <div class="plan-page" ref="pageRef">
    <!-- Initial page loading -->
    <div v-if="initialLoading" class="loading-state">
      <div class="skeleton skeleton-line" style="width:200px;height:24px;margin:var(--space-8) auto"></div>
    </div>

    <!-- Agent followup: info incomplete -->
    <div v-if="followup && !loading" class="followup-state">
      <div class="followup-icon">&#128172;</div>
      <h2>还需要补充一些信息</h2>
      <div class="followup-content">
        <p class="followup-text">{{ followup.followup_questions }}</p>
        <div class="followup-details" v-if="followup.missing_fields.length">
          <span class="followup-label">待补充：</span>
          <span v-for="(f, i) in followup.missing_fields" :key="i" class="followup-tag">{{ f }}</span>
        </div>
        <div class="followup-details" v-if="followup.field_warnings.length">
          <span class="followup-label followup-label--warn">需确认：</span>
          <span v-for="(w, i) in followup.field_warnings" :key="i" class="followup-tag followup-tag--warn">{{ w }}</span>
        </div>
      </div>
      <div class="followup-actions">
        <button class="btn btn-primary" @click="router.push('/profile')">去补充信息</button>
        <button class="btn btn-ghost" @click="fetchPlan">重新检测</button>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="!plan && !loading && !followup" class="empty-state">
      <div class="empty-icon">&#9201;</div>
      <h2>还没有生成计划</h2>
      <p>AI 会根据你的身体数据量身定制饮食和运动方案。</p>
      <button class="btn btn-primary" @click="fetchPlan">生成训练计划</button>
    </div>

    <!-- Generating -->
    <div v-if="loading" class="skeleton-page">
      <div class="loading-progress">
        <p class="wait-message">{{ waitMessage }}</p>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
        </div>
        <p class="progress-label">{{ progressLabel }}</p>
      </div>
      <div class="skeleton-hero">
        <div class="skeleton skeleton-number"></div>
        <div class="skeleton skeleton-unit"></div>
      </div>
      <div class="skeleton-macros">
        <div class="skeleton skeleton-card" v-for="i in 4" :key="i"></div>
      </div>
      <div class="skeleton-tabs">
        <div class="skeleton skeleton-tab" v-for="i in 3" :key="i"></div>
      </div>
      <div class="skeleton-lines">
        <div class="skeleton skeleton-line" v-for="i in 6" :key="i"></div>
      </div>
    </div>

    <!-- Plan content -->
    <template v-if="plan && !loading && !initialLoading">
      <!-- Primary metric -->
      <div class="hero-metric">
        <span class="metric-value">{{ plan.calorie_info.target_calories }}</span>
        <span class="metric-unit">kcal / 天</span>
        <span class="metric-label">每日热量目标</span>
      </div>

      <!-- Macros row -->
      <div class="metric-row">
        <div class="metric-card">
          <span class="metric-card-label">蛋白质</span>
          <span class="metric-card-value">{{ plan.macros.protein_g }}<small>g</small></span>
        </div>
        <div class="metric-card">
          <span class="metric-card-label">碳水</span>
          <span class="metric-card-value">{{ plan.macros.carbs_g }}<small>g</small></span>
        </div>
        <div class="metric-card">
          <span class="metric-card-label">脂肪</span>
          <span class="metric-card-value">{{ plan.macros.fat_g }}<small>g</small></span>
        </div>
        <div class="metric-card metric-card--secondary">
          <span class="metric-card-label">饮水</span>
          <span class="metric-card-value">{{ plan.macros.water_ml }}<small>ml</small></span>
        </div>
      </div>

      <!-- Goal type badge -->
      <div class="goal-badge" v-if="plan.calorie_info.goal_type">
        <span class="goal-badge-tag" :class="plan.calorie_info.goal_type === 'muscle_gain' ? 'goal-badge--gain' : 'goal-badge--loss'">
          {{ plan.calorie_info.goal_type === 'muscle_gain' ? '&#128170; 增肌' : '&#128293; 减脂' }}
        </span>
        <span class="goal-badge-strategy">{{ plan.calorie_info.strategy === 'lean_bulk' ? '精益增重' : '热量缺口' }}</span>
      </div>

      <!-- Detail metrics -->
      <div class="detail-row">
        <div class="detail-item">
          <span class="detail-label">BMR</span>
          <span class="detail-value">{{ plan.calorie_info.bmr }} kcal</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">TDEE</span>
          <span class="detail-value">{{ plan.calorie_info.tdee }} kcal</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">{{ plan.calorie_info.goal_type === 'muscle_gain' ? '热量盈余' : '热量缺口' }}</span>
          <span class="detail-value">{{ plan.calorie_info.deficit }} kcal</span>
        </div>
      </div>

      <!-- Plan meta -->
      <div class="plan-meta" v-if="plan.created_at">
        <span class="plan-date">生成于 {{ plan.created_at.slice(0, 10) }}</span>
        <button class="btn btn-ghost btn--sm" :disabled="loading" @click="fetchPlan">重新生成</button>
      </div>

      <!-- Plan tabs -->
      <div class="plan-section">
        <div class="tab-bar">
          <button
            v-for="tab in [
              { key: 'meal', label: '饮食计划' },
              { key: 'workout', label: '运动计划' },
              { key: 'summary', label: '总结建议' },
            ]"
            :key="tab.key"
            class="tab-btn"
            :class="{ 'tab-btn--active': activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- 运动计划：结构化渲染 -->
        <div v-if="activeTab === 'workout' && structuredWorkout" class="workout-structured">
          <!-- 排除动作 -->
          <div v-if="structuredWorkout.excluded.length" class="excluded-section">
            <h4 class="excluded-title">已排除（伤病安全）</h4>
            <div v-for="ex in structuredWorkout.excluded" :key="ex.exercise_id" class="excluded-item">
              <span class="excluded-id">{{ ex.exercise_id }}</span>
              <span class="excluded-reason">{{ ex.reason }}</span>
            </div>
          </div>

          <!-- 每日计划 -->
          <div v-for="day in structuredWorkout.weekly_plan" :key="day.day" class="workout-day">
            <div class="day-header">
              <span class="day-number">第{{ day.day }}天</span>
              <span class="day-theme">{{ day.theme }}</span>
              <span class="day-duration" v-if="day.duration_minutes">{{ day.duration_minutes }}分钟</span>
            </div>

            <div v-if="day.theme === 'rest' || day.theme === '休息'" class="day-rest">休息日</div>

            <div v-else class="exercise-list">
              <div
                v-for="ex in day.exercises"
                :key="ex.exercise_id"
                class="exercise-card"
                :class="{ 'exercise-card--expanded': expandedExercises.has(ex.exercise_id) }"
              >
                <div class="exercise-header" @click="toggleExercise(ex.exercise_id)">
                  <span class="exercise-name">
                    {{ exerciseCache[ex.exercise_id]?.name_zh || exerciseCache[ex.exercise_id]?.name || ex.exercise_id }}
                  </span>
                  <span class="exercise-sets">{{ ex.sets }} × {{ ex.reps }}</span>
                  <span class="exercise-rest" v-if="ex.rest_seconds">{{ ex.rest_seconds }}s休息</span>
                  <span class="exercise-toggle">{{ expandedExercises.has(ex.exercise_id) ? '▾' : '▸' }}</span>
                </div>

                <div v-if="expandedExercises.has(ex.exercise_id)" class="exercise-detail">
                  <div v-if="loadingExercises.has(ex.exercise_id)" class="exercise-loading">加载中...</div>
                  <template v-else-if="exerciseCache[ex.exercise_id]">
                    <div class="exercise-media" v-if="exerciseCache[ex.exercise_id].gif_url">
                      <img
                        :src="exerciseCache[ex.exercise_id].gif_url"
                        :alt="exerciseCache[ex.exercise_id].name_zh"
                        class="exercise-gif"
                      />
                      <span class="exercise-attribution">© Gym visual</span>
                    </div>
                    <div class="exercise-steps">
                      <div class="exercise-meta">
                        <span>部位: {{ exerciseCache[ex.exercise_id].body_part }}</span>
                        <span>器械: {{ exerciseCache[ex.exercise_id].equipment }}</span>
                        <span>目标: {{ exerciseCache[ex.exercise_id].target }}</span>
                      </div>
                      <ol class="steps-list">
                        <li v-for="(step, i) in exerciseCache[ex.exercise_id].instruction_steps_zh" :key="i">{{ step }}</li>
                      </ol>
                    </div>
                  </template>
                  <div v-else class="exercise-loading">详情加载失败</div>
                </div>
              </div>

              <!-- 有氧 -->
              <div v-if="day.cardio" class="cardio-row">
                <span class="cardio-label">有氧</span>
                <span class="cardio-detail">{{ day.cardio.type }} {{ day.cardio.duration_minutes }}分钟 · {{ day.cardio.intensity }}</span>
              </div>
            </div>
          </div>

          <!-- 热身和注意事项 -->
          <div v-if="structuredWorkout.warmup?.length" class="workout-extras">
            <h4>热身建议</h4>
            <ul><li v-for="(w, i) in structuredWorkout.warmup" :key="i">{{ w }}</li></ul>
          </div>
          <div v-if="structuredWorkout.notes?.length" class="workout-extras">
            <h4>注意事项</h4>
            <ul><li v-for="(n, i) in structuredWorkout.notes" :key="i">{{ n }}</li></ul>
          </div>
        </div>

        <!-- 文本兜底（饮食、总结、或老计划无 JSON） -->
        <div
          v-else
          class="plan-content"
          v-html="formatPlan(
            activeTab === 'meal' ? plan.meal_plan :
            activeTab === 'workout' ? plan.workout_plan :
            plan.summary
          )"
        ></div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.plan-page {
  max-width: 800px;
  margin: 0 auto;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: var(--space-12) 0;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--space-4);
  opacity: 0.3;
}

.empty-state h2 {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-2);
}

.empty-state p {
  color: var(--color-text-secondary);
  margin-bottom: var(--space-6);
}

/* Followup state */
.followup-state {
  text-align: center;
  padding: var(--space-10) 0;
}

.followup-icon {
  font-size: 48px;
  margin-bottom: var(--space-4);
  opacity: 0.6;
}

.followup-state h2 {
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-5);
}

.followup-content {
  max-width: 500px;
  margin: 0 auto var(--space-6);
  text-align: left;
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}

.followup-text {
  font-size: var(--text-base);
  color: var(--color-text-primary);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-4);
  white-space: pre-wrap;
}

.followup-details {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.followup-label {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-accent);
}

.followup-label--warn {
  color: var(--color-warning);
}

.followup-tag {
  font-size: var(--text-xs);
  padding: 2px var(--space-2);
  background: var(--color-accent-subtle);
  color: var(--color-accent);
  border-radius: var(--radius-sm);
  font-weight: 500;
}

.followup-tag--warn {
  background: oklch(0.95 0.04 80);
  color: oklch(0.45 0.12 80);
}

.followup-actions {
  display: flex;
  justify-content: center;
  gap: var(--space-3);
}

/* Skeleton loading */
.skeleton-page {
  padding: var(--space-8) 0;
}

.loading-progress {
  margin-bottom: var(--space-6);
  text-align: center;
}

.progress-bar {
  height: 4px;
  background: var(--color-border-subtle);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: var(--space-3);
}

.progress-fill {
  height: 100%;
  background: var(--color-accent);
  border-radius: 2px;
  transition: width 1s var(--ease-out);
}

.progress-label {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-weight: 500;
}

.wait-message {
  font-size: var(--text-base);
  color: var(--color-text-primary);
  font-weight: 500;
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-4);
}

.skeleton-hero {
  text-align: center;
  padding: var(--space-6) 0 var(--space-5);
}

.skeleton-number {
  display: inline-block;
  width: 160px;
  height: 56px;
  border-radius: var(--radius-sm);
}

.skeleton-unit {
  display: block;
  width: 100px;
  height: 20px;
  margin: var(--space-3) auto 0;
  border-radius: var(--radius-sm);
}

.skeleton-macros {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-6);
}

.skeleton-card {
  height: 72px;
  border-radius: var(--radius-md);
}

.skeleton-tabs {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border-subtle);
}

.skeleton-tab {
  width: 80px;
  height: 20px;
  border-radius: var(--radius-sm);
}

.skeleton-lines {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skeleton-line {
  height: 16px;
  border-radius: var(--radius-sm);
}

.skeleton-line:nth-child(1) { width: 100%; }
.skeleton-line:nth-child(2) { width: 85%; }
.skeleton-line:nth-child(3) { width: 92%; }
.skeleton-line:nth-child(4) { width: 78%; }
.skeleton-line:nth-child(5) { width: 95%; }
.skeleton-line:nth-child(6) { width: 60%; }

.loading-hint {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  text-align: center;
  margin-top: var(--space-6);
}

/* Hero metric */
.hero-metric {
  text-align: center;
  padding: var(--space-8) 0 var(--space-6);
}

.metric-value {
  font-family: var(--font-mono);
  font-size: 56px;
  font-weight: 800;
  color: var(--color-text-primary);
  letter-spacing: -0.03em;
  line-height: 1;
}

.metric-unit {
  display: block;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--color-accent);
  margin-top: var(--space-2);
}

.metric-label {
  display: block;
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin-top: var(--space-1);
}

/* Macros row */
.metric-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.metric-card {
  background: var(--color-accent-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  text-align: center;
}

.metric-card--secondary {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
}

.metric-card-label {
  display: block;
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-1);
}

.metric-card-value {
  font-family: var(--font-mono);
  font-size: var(--text-xl);
  font-weight: 700;
  color: var(--color-text-primary);
}

.metric-card-value small {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-left: 2px;
}

/* Goal badge */
.goal-badge {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  justify-content: center;
  margin-bottom: var(--space-4);
}

.goal-badge-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  padding: 0 var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: 700;
}

.goal-badge--loss {
  background: oklch(0.93 0.06 25);
  color: oklch(0.45 0.14 25);
}

.goal-badge--gain {
  background: oklch(0.93 0.06 145);
  color: oklch(0.40 0.12 145);
}

.goal-badge-strategy {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

/* Detail row */
.detail-row {
  display: flex;
  gap: var(--space-6);
  padding: var(--space-4) 0;
  border-top: 1px solid var(--color-border-subtle);
  border-bottom: 1px solid var(--color-border-subtle);
  margin-bottom: var(--space-8);
}

.detail-item {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.detail-label {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

.detail-value {
  font-family: var(--font-mono);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text-secondary);
}

/* Plan meta */
.plan-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) 0;
  margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border-subtle);
}

.plan-date {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  font-family: var(--font-mono);
}

.btn--sm {
  height: 32px;
  padding: 0 var(--space-3);
  font-size: var(--text-sm);
}

.btn-ghost {
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.btn-ghost:hover:not(:disabled) {
  border-color: var(--color-text-tertiary);
}

.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Plan section */
.plan-section {
  margin-top: var(--space-4);
}

.tab-bar {
  display: flex;
  gap: var(--space-1);
  margin-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-border-subtle);
  padding-bottom: 0;
}

.tab-btn {
  padding: var(--space-3) var(--space-4);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  margin-bottom: -1px;
}

.tab-btn:hover {
  color: var(--color-text-primary);
}

.tab-btn--active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}

.plan-content {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  color: var(--color-text-primary);
  max-width: 65ch;
}

.plan-content :deep(strong) {
  font-weight: 700;
  color: var(--color-text-primary);
}

.plan-content :deep(h4) {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text-primary);
  margin: var(--space-6) 0 var(--space-3);
}

/* Button */
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

@media (max-width: 640px) {
  .metric-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .skeleton-macros {
    grid-template-columns: repeat(2, 1fr);
  }
  .detail-row {
    flex-direction: column;
    gap: var(--space-2);
  }
  .metric-value {
    font-size: 40px;
  }
  .exercise-detail {
    flex-direction: column !important;
  }
  .exercise-gif {
    width: 120px !important;
    height: 120px !important;
  }
}

/* Structured workout plan */
.workout-structured {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.excluded-section {
  background: oklch(0.96 0.03 80);
  border: 1px solid oklch(0.88 0.05 80);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

.excluded-title {
  font-size: var(--text-sm);
  font-weight: 700;
  color: oklch(0.45 0.12 80);
  margin-bottom: var(--space-2);
}

.excluded-item {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
}

.excluded-id {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--color-text-tertiary);
  flex-shrink: 0;
}

.workout-day {
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.day-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-accent-subtle);
}

.day-number {
  font-weight: 700;
  font-size: var(--text-base);
  color: var(--color-accent);
}

.day-theme {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  flex: 1;
}

.day-duration {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-family: var(--font-mono);
}

.day-rest {
  padding: var(--space-4);
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--text-sm);
}

.exercise-list {
  padding: var(--space-2) var(--space-4) var(--space-3);
}

.exercise-card {
  border-bottom: 1px solid var(--color-border-subtle);
}

.exercise-card:last-child {
  border-bottom: none;
}

.exercise-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
  border-radius: var(--radius-sm);
  padding-left: var(--space-2);
  padding-right: var(--space-2);
}

.exercise-header:hover {
  background: var(--color-accent-subtle);
}

.exercise-name {
  flex: 1;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
}

.exercise-sets {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-accent);
}

.exercise-rest {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.exercise-toggle {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  width: 16px;
  text-align: center;
}

.exercise-detail {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-3) var(--space-2) var(--space-4);
}

.exercise-media {
  flex-shrink: 0;
  position: relative;
}

.exercise-gif {
  width: 180px;
  height: 180px;
  border-radius: var(--radius-sm);
  object-fit: cover;
}

.exercise-attribution {
  display: block;
  font-size: 10px;
  color: var(--color-text-tertiary);
  text-align: center;
  margin-top: 2px;
}

.exercise-steps {
  flex: 1;
  min-width: 0;
}

.exercise-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.exercise-meta span {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  background: var(--color-surface);
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
}

.steps-list {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  padding-left: var(--space-5);
}

.steps-list li {
  margin-bottom: var(--space-1);
}

.exercise-loading {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  padding: var(--space-2) 0;
}

.cardio-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  margin-top: var(--space-2);
}

.cardio-label {
  font-size: var(--text-xs);
  font-weight: 700;
  color: var(--color-accent);
  text-transform: uppercase;
}

.cardio-detail {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.workout-extras {
  background: var(--color-surface);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

.workout-extras h4 {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-2);
}

.workout-extras ul {
  padding-left: var(--space-5);
}

.workout-extras li {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  margin-bottom: var(--space-1);
}
</style>
