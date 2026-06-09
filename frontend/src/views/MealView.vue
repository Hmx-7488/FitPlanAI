<script setup lang="ts">
defineOptions({ name: 'MealView' })
import { ref, computed, nextTick, onMounted, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { recognizeMeal, calculateMeal, getMealDailySummary } from '../api'
import type { MealAnalysis, MealDailySummary } from '../api'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const calculating = ref(false)
const mealType = ref('lunch')
const dailySummary = ref<MealDailySummary | null>(null)
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')

// 每个餐食类型独立保存状态
interface MealState {
  step: 'upload' | 'recognizing' | 'confirm' | 'calculating' | 'result'
  selectedFile: File | null
  previewUrl: string
  recognitionId: string
  ingredients: Array<{
    name: string
    display_name: string
    estimated_weight_g: number
    confidence: number
  }>
  result: MealAnalysis | null
}

const mealStates = ref<Record<string, MealState>>({
  breakfast: { step: 'upload', selectedFile: null, previewUrl: '', recognitionId: '', ingredients: [], result: null },
  lunch: { step: 'upload', selectedFile: null, previewUrl: '', recognitionId: '', ingredients: [], result: null },
  dinner: { step: 'upload', selectedFile: null, previewUrl: '', recognitionId: '', ingredients: [], result: null },
  snack: { step: 'upload', selectedFile: null, previewUrl: '', recognitionId: '', ingredients: [], result: null },
})

// 计算当前选中餐食类型的状态
const currentState = computed(() => mealStates.value[mealType.value])
const step = computed(() => currentState.value.step)
const selectedFile = computed(() => currentState.value.selectedFile)
const previewUrl = computed(() => currentState.value.previewUrl)
const ingredients = computed(() => currentState.value.ingredients)
const result = computed(() => currentState.value.result)
const summaryProgress = computed(() => Math.min(dailySummary.value?.progress_pct ?? 0, 100))

function animateResult() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.result-header, .photo-preview'), { y: 20, opacity: 0, duration: 0.4 })
    tl.from(pageRef.value.querySelectorAll('.total-card'), { y: 30, opacity: 0, scale: 0.95, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.summary-card'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.items-card'), { y: 20, opacity: 0, duration: 0.4 }, '-=0.2')
    // 热量数字滚动
    const calEl = pageRef.value.querySelector('.total-value') as HTMLElement
    if (calEl) {
      const target = parseInt(calEl.textContent || '0')
      const obj = { val: 0 }
      gsap.to(obj, { val: target, duration: 1, ease: 'power2.out', delay: 0.3, onUpdate() { calEl.textContent = Math.round(obj.val).toString() } })
    }
  })
}

watch(result, (val) => { if (val) animateResult() })

const mealTypeOptions = [
  { value: 'breakfast', label: '早餐' },
  { value: 'lunch', label: '午餐' },
  { value: 'dinner', label: '晚餐' },
  { value: 'snack', label: '加餐' },
]

function mealLabel(type: string): string {
  return mealTypeOptions.find(o => o.value === type)?.label || type
}

async function refreshDailySummary() {
  const userId = localStorage.getItem('userId')
  if (!userId) return
  try {
    const summary = await getMealDailySummary(Number(userId))
    dailySummary.value = summary
    for (const opt of mealTypeOptions) {
      const meal = summary.meals[opt.value]
      if (!meal) continue
      mealStates.value[opt.value].step = 'result'
      mealStates.value[opt.value].previewUrl = meal.image_url
      mealStates.value[opt.value].result = {
        meal_type: opt.value,
        items: meal.items,
        meal_total: meal.meal_total,
        daily_summary: {
          daily_target_kcal: summary.daily_target_kcal,
          estimated_tdee_kcal: summary.estimated_tdee_kcal,
          consumed_kcal: summary.consumed_kcal,
          remaining_target_kcal: summary.remaining_target_kcal,
          current_deficit_kcal: summary.current_deficit_kcal,
          status: summary.status,
          suggestion: summary.suggestion,
        },
      }
    }
  } catch {
    dailySummary.value = null
  }
}

onMounted(() => {
  void refreshDailySummary()
})

// 切换餐食类型时清空文件输入
watch(mealType, () => {
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
})

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  // 更新当前餐食类型的状态
  mealStates.value[mealType.value].selectedFile = file
  mealStates.value[mealType.value].previewUrl = URL.createObjectURL(file)
}

async function doRecognize() {
  if (!currentState.value.selectedFile) return
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  mealStates.value[mealType.value].step = 'recognizing'
  loading.value = true

  try {
    const res = await recognizeMeal(Number(userId), currentState.value.selectedFile, mealType.value)
    mealStates.value[mealType.value].recognitionId = res.recognition_id
    mealStates.value[mealType.value].ingredients = res.ingredients.map(i => ({ ...i }))
    mealStates.value[mealType.value].step = 'confirm'
    ElMessage.success('识别完成，请确认食材')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '识别失败')
    mealStates.value[mealType.value].step = 'upload'
  } finally {
    loading.value = false
  }
}

function updateWeight(index: number, value: string) {
  const num = parseFloat(value)
  if (!isNaN(num) && num > 0) {
    mealStates.value[mealType.value].ingredients[index].estimated_weight_g = num
  }
}

function removeIngredient(index: number) {
  mealStates.value[mealType.value].ingredients.splice(index, 1)
}

function addIngredient() {
  mealStates.value[mealType.value].ingredients.push({
    name: 'custom',
    display_name: '',
    estimated_weight_g: 100,
    confidence: 1.0,
  })
}

async function doCalculate() {
  const state = mealStates.value[mealType.value]
  if (state.ingredients.length === 0) {
    ElMessage.warning('请至少保留一个食材')
    return
  }

  // 过滤掉空名称的
  const valid = state.ingredients.filter(i => i.display_name.trim())
  if (valid.length === 0) {
    ElMessage.warning('请至少保留一个食材')
    return
  }

  calculating.value = true
  mealStates.value[mealType.value].step = 'calculating'

  try {
    const res = await calculateMeal({
      recognition_id: state.recognitionId,
      ingredients: valid,
      meal_type: mealType.value,
    })
    mealStates.value[mealType.value].result = res
    mealStates.value[mealType.value].step = 'result'
    await refreshDailySummary()
    ElMessage.success('计算完成')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '计算失败')
    mealStates.value[mealType.value].step = 'confirm'
  } finally {
    calculating.value = false
  }
}

function resetCurrentMeal() {
  mealStates.value[mealType.value] = {
    step: 'upload',
    selectedFile: null,
    previewUrl: '',
    recognitionId: '',
    ingredients: [],
    result: null
  }
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
}

function statusColor(status: string): string {
  if (status === 'on_track') return 'var(--color-accent)'
  if (status === 'near_target') return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    on_track: '正常',
    near_target: '接近目标',
    over_target: '超标',
    deficit_too_large: '缺口过大',
  }
  return map[status] || status
}
</script>

<template>
  <div class="meal-page" ref="pageRef">
    <div class="page-header">
      <h1>餐食热量识别</h1>
      <p>拍照识别已吃的餐食，AI 估算热量并计算每日缺口。</p>
    </div>

    <!-- 餐次选择（常驻显示） -->
    <section v-if="dailySummary" class="daily-total-card">
      <div class="daily-total-main">
        <div>
          <span class="summary-label">今日已摄入</span>
          <strong>{{ dailySummary.consumed_kcal }}</strong>
          <span>kcal</span>
        </div>
        <div>
          <span class="summary-label">今日目标</span>
          <strong>{{ dailySummary.daily_target_kcal }}</strong>
          <span>kcal</span>
        </div>
        <div>
          <span class="summary-label">剩余额度</span>
          <strong>{{ dailySummary.remaining_target_kcal }}</strong>
          <span>kcal</span>
        </div>
      </div>
      <div class="daily-progress">
        <div class="daily-progress-fill" :style="{ width: `${summaryProgress}%` }"></div>
      </div>
      <div class="daily-meal-grid">
        <button
          v-for="opt in mealTypeOptions"
          :key="opt.value"
          class="daily-meal-chip"
          :class="{ 'daily-meal-chip--active': mealType === opt.value }"
          @click="mealType = opt.value"
        >
          <span>{{ mealLabel(opt.value) }}</span>
          <strong>{{ dailySummary.meals[opt.value]?.meal_total.calories_kcal ?? 0 }} kcal</strong>
        </button>
      </div>
      <p class="daily-suggestion">{{ dailySummary.suggestion }}</p>
    </section>

    <div class="meal-type-select">
      <label class="field-label">餐次</label>
      <div class="radio-group">
        <button
          v-for="opt in mealTypeOptions"
          :key="opt.value"
          class="radio-btn"
          :class="{ 'radio-btn--active': mealType === opt.value, 'radio-btn--done': mealStates[opt.value].step === 'result' }"
          @click="mealType = opt.value"
        >
          {{ opt.label }}
          <span v-if="mealStates[opt.value].step === 'result'" class="done-dot"></span>
        </button>
      </div>
    </div>

    <!-- Step 1: Upload -->
    <div v-if="step === 'upload'" class="upload-section">
      <div class="upload-area" @click="fileInputRef?.click()">
        <div v-if="previewUrl" class="preview">
          <img :src="previewUrl" alt="预览" />
        </div>
        <div v-else class="upload-placeholder">
          <span class="upload-icon">&#127860;</span>
          <p>点击上传{{ mealTypeOptions.find(o => o.value === mealType)?.label }}照片</p>
          <span class="upload-hint">拍摄你正在吃或已吃的食物</span>
        </div>
      </div>
      <input ref="fileInputRef" type="file" accept="image/*" style="display:none" @change="onFileChange" />
      <div class="upload-actions">
        <button class="btn btn-primary" :disabled="!selectedFile || loading" @click="doRecognize">
          {{ loading ? '识别中...' : '开始识别' }}
        </button>
      </div>
    </div>

    <!-- Step 2: Recognizing -->
    <div v-if="step === 'recognizing'" class="loading-section">
      <div class="loading-icon">&#128270;</div>
      <p class="loading-msg">AI 正在识别食材...</p>
      <div class="loading-bar"><div class="loading-fill"></div></div>
      <p class="loading-hint">Vision Model 正在分析图片，约需 10-30 秒</p>
    </div>

    <!-- Step 3: Confirm ingredients -->
    <div v-if="step === 'confirm'" class="confirm-section">
      <div class="confirm-header">
        <h2>食材识别结果</h2>
        <p>请确认食材和重量，可修改或删除。</p>
      </div>

      <!-- 预览图 -->
      <div class="confirm-preview" v-if="previewUrl">
        <img :src="previewUrl" alt="餐食照片" />
      </div>

      <!-- 食材列表 -->
      <div class="ingredient-list">
        <div
          v-for="(item, index) in ingredients"
          :key="index"
          class="ingredient-card"
        >
          <div class="ingredient-info">
            <input
              v-model="item.display_name"
              class="ingredient-name-input"
              placeholder="食材名称"
            />
            <span class="confidence" v-if="item.confidence < 1">
              置信度 {{ (item.confidence * 100).toFixed(0) }}%
            </span>
          </div>
          <div class="ingredient-weight">
            <input
              type="number"
              :value="item.estimated_weight_g"
              @input="updateWeight(index, ($event.target as HTMLInputElement).value)"
              min="1" max="5000" step="10"
              class="weight-input"
            />
            <span class="weight-unit">g</span>
          </div>
          <button class="remove-btn" @click="removeIngredient(index)">&times;</button>
        </div>
      </div>

      <div class="confirm-actions">
        <button class="btn btn-secondary" @click="addIngredient">+ 添加食材</button>
        <button class="btn btn-primary" :disabled="calculating" @click="doCalculate">
          {{ calculating ? '计算中...' : '确认并计算热量' }}
        </button>
        <button class="btn btn-ghost" @click="resetCurrentMeal">重新拍照</button>
      </div>
    </div>

    <!-- Step 4: Calculating -->
    <div v-if="step === 'calculating'" class="loading-section">
      <div class="loading-icon">&#127859;</div>
      <p class="loading-msg">正在计算营养成分...</p>
      <div class="loading-bar"><div class="loading-fill"></div></div>
    </div>

    <!-- Step 5: Result -->
    <div v-if="step === 'result' && result" class="result-section">
      <div class="result-header">
        <h2>{{ mealTypeOptions.find(o => o.value === mealType)?.label }}识别结果</h2>
      </div>

      <!-- Photo preview -->
      <div class="photo-preview" v-if="previewUrl">
        <img :src="previewUrl" alt="餐食照片" />
      </div>

      <!-- Meal total -->
      <div class="total-card">
        <div class="total-main">
          <span class="total-value">{{ result.meal_total.calories_kcal }}</span>
          <span class="total-unit">kcal</span>
        </div>
        <div class="total-macros">
          <span class="macro">蛋白 {{ result.meal_total.protein_g.toFixed(0) }}g</span>
          <span class="macro">碳水 {{ result.meal_total.carbs_g.toFixed(0) }}g</span>
          <span class="macro">脂肪 {{ result.meal_total.fat_g.toFixed(0) }}g</span>
        </div>
      </div>

      <!-- Daily summary -->
      <div class="summary-card" v-if="result.daily_summary">
        <h3>今日热量状态</h3>
        <div class="summary-status">
          <span class="status-dot" :style="{ background: statusColor(result.daily_summary.status) }"></span>
          <span class="status-text" :style="{ color: statusColor(result.daily_summary.status) }">{{ statusLabel(result.daily_summary.status) }}</span>
        </div>
        <div class="summary-grid">
          <div class="summary-item">
            <span class="summary-label">目标</span>
            <span class="summary-value">{{ result.daily_summary.daily_target_kcal }} kcal</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">已摄入</span>
            <span class="summary-value">{{ result.daily_summary.consumed_kcal }} kcal</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">剩余</span>
            <span class="summary-value">{{ result.daily_summary.remaining_target_kcal }} kcal</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">当前缺口</span>
            <span class="summary-value">{{ result.daily_summary.current_deficit_kcal }} kcal</span>
          </div>
        </div>
        <p class="summary-suggestion">{{ result.daily_summary.suggestion }}</p>
      </div>

      <!-- Items list -->
      <div class="items-card" v-if="result.items.length">
        <h3>识别菜品</h3>
        <div v-for="(item, i) in result.items" :key="i" class="item-row">
          <span class="item-name">{{ item.dish_name }}</span>
          <span class="item-portion">{{ item.estimated_portion_g }}g</span>
          <span class="item-cal">{{ item.calories_kcal }} kcal</span>
        </div>
      </div>

      <div class="result-actions">
        <button class="btn btn-primary" @click="resetCurrentMeal">再拍一张</button>
        <button class="btn btn-ghost" @click="router.push('/history')">查看历史</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.meal-page { max-width: 640px; margin: 0 auto; }
.page-header { margin-bottom: var(--space-8); }
.page-header h1 { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); margin-bottom: var(--space-2); }
.page-header p { font-size: var(--text-md); color: var(--color-text-secondary); }

.daily-total-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  margin-bottom: var(--space-5);
}
.daily-total-main {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.daily-total-main div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.daily-total-main strong {
  font-family: var(--font-mono);
  font-size: var(--text-xl);
  color: var(--color-text-primary);
}
.daily-progress {
  height: 8px;
  background: var(--color-border-subtle);
  border-radius: 999px;
  overflow: hidden;
  margin-bottom: var(--space-4);
}
.daily-progress-fill {
  height: 100%;
  background: var(--color-accent);
  border-radius: 999px;
  transition: width var(--duration-normal) var(--ease-out);
}
.daily-meal-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.daily-meal-chip {
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
  cursor: pointer;
  text-align: left;
}
.daily-meal-chip span {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
.daily-meal-chip strong {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--color-text-primary);
}
.daily-meal-chip--active {
  border-color: var(--color-accent);
  background: var(--color-accent-subtle);
}
.daily-suggestion {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
  margin: 0;
}

.meal-type-select { margin-bottom: var(--space-5); }
.field-label { display: block; font-size: var(--text-sm); font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-2); }
.radio-group { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.radio-btn { position: relative; height: 40px; padding: 0 var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); font-size: var(--text-base); font-family: var(--font-family); color: var(--color-text-secondary); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.radio-btn:hover { border-color: var(--color-accent); color: var(--color-text-primary); }
.radio-btn--active { border-color: var(--color-accent); background: var(--color-accent-subtle); color: var(--color-accent); font-weight: 600; }
.radio-btn--done { border-color: var(--color-accent); }
.done-dot { position: absolute; top: 4px; right: 4px; width: 8px; height: 8px; border-radius: 50%; background: var(--color-accent); }

.upload-section { text-align: center; }
.upload-area { border: 2px dashed var(--color-border); border-radius: var(--radius-md); padding: var(--space-10); cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out); margin-bottom: var(--space-5); }
.upload-area:hover { border-color: var(--color-accent); }
.upload-placeholder { color: var(--color-text-tertiary); }
.upload-icon { font-size: 48px; display: block; margin-bottom: var(--space-3); opacity: 0.4; }
.upload-hint { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.preview img { max-width: 100%; max-height: 300px; border-radius: var(--radius-sm); }
.upload-actions { display: flex; justify-content: center; gap: var(--space-3); }

/* Loading */
.loading-section { text-align: center; padding: var(--space-12) 0; }
.loading-icon { font-size: 48px; margin-bottom: var(--space-4); opacity: 0.5; }
.loading-msg { font-size: var(--text-md); font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-4); }
.loading-bar { height: 4px; background: var(--color-border-subtle); border-radius: 2px; overflow: hidden; max-width: 300px; margin: 0 auto var(--space-3); }
.loading-fill { height: 100%; background: var(--color-accent); border-radius: 2px; animation: loadPulse 2s ease-in-out infinite; width: 60%; }
@keyframes loadPulse { 0%,100% { width: 30%; } 50% { width: 80%; } }
.loading-hint { font-size: var(--text-sm); color: var(--color-text-tertiary); }

/* Confirm */
.confirm-section { display: flex; flex-direction: column; gap: var(--space-4); }
.confirm-header { margin-bottom: var(--space-2); }
.confirm-header h2 { font-size: var(--text-xl); font-weight: 700; margin-bottom: var(--space-1); }
.confirm-header p { color: var(--color-text-secondary); }
.confirm-preview { margin-bottom: var(--space-2); }
.confirm-preview img { max-width: 100%; max-height: 200px; border-radius: var(--radius-sm); }

.ingredient-list { display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-4); }
.ingredient-card {
  display: flex; align-items: center; gap: var(--space-3);
  background: var(--color-surface); border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md); padding: var(--space-3) var(--space-4);
}
.ingredient-info { flex: 1; display: flex; align-items: center; gap: var(--space-2); }
.ingredient-name-input {
  border: none; background: transparent; font-size: var(--text-base); font-weight: 600;
  color: var(--color-text-primary); width: 120px; outline: none;
  border-bottom: 1px solid transparent;
}
.ingredient-name-input:focus { border-bottom-color: var(--color-accent); }
.confidence { font-size: var(--text-xs); color: var(--color-text-tertiary); background: var(--color-surface); padding: 1px 6px; border-radius: 4px; }
.ingredient-weight { display: flex; align-items: center; gap: 4px; }
.weight-input {
  width: 70px; height: 36px; text-align: center; border: 1px solid var(--color-border);
  border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: var(--text-base);
  color: var(--color-text-primary); background: var(--color-surface); outline: none;
}
.weight-input:focus { border-color: var(--color-accent); }
.weight-unit { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.remove-btn { background: none; border: none; font-size: 18px; color: var(--color-text-tertiary); cursor: pointer; padding: 4px; }
.remove-btn:hover { color: var(--color-danger); }

.confirm-actions { display: flex; gap: var(--space-3); flex-wrap: wrap; }

.result-section { display: flex; flex-direction: column; gap: var(--space-4); }
.result-header h2 { font-size: var(--text-xl); font-weight: 700; }

.photo-preview img { max-width: 100%; max-height: 200px; border-radius: var(--radius-sm); }

.total-card { text-align: center; background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-6); }
.total-main { display: flex; align-items: baseline; justify-content: center; gap: var(--space-2); margin-bottom: var(--space-3); }
.total-value { font-family: var(--font-mono); font-size: 48px; font-weight: 800; color: var(--color-text-primary); line-height: 1; }
.total-unit { font-size: var(--text-md); color: var(--color-text-tertiary); }
.total-macros { display: flex; justify-content: center; gap: var(--space-4); }
.macro { font-size: var(--text-sm); color: var(--color-text-secondary); font-family: var(--font-mono); }

.summary-card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.summary-card h3 { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-3); }
.summary-status { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-3); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; }
.status-text { font-size: var(--text-sm); font-weight: 600; }
.summary-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); margin-bottom: var(--space-3); }
.summary-item { display: flex; flex-direction: column; }
.summary-label { font-size: var(--text-xs); color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: 0.06em; }
.summary-value { font-family: var(--font-mono); font-size: var(--text-base); font-weight: 600; color: var(--color-text-primary); }
.summary-suggestion { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); background: var(--color-accent-subtle); padding: var(--space-3); border-radius: var(--radius-sm); }

.items-card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.items-card h3 { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-3); }
.item-row { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) 0; border-bottom: 1px solid var(--color-border-subtle); }
.item-row:last-child { border-bottom: none; }
.item-name { flex: 1; font-weight: 600; color: var(--color-text-primary); }
.item-portion { font-size: var(--text-sm); color: var(--color-text-tertiary); font-family: var(--font-mono); }
.item-cal { font-size: var(--text-sm); font-weight: 600; color: var(--color-accent); font-family: var(--font-mono); }
.item-confidence { font-size: var(--text-xs); color: var(--color-text-tertiary); padding: 1px 6px; background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: 4px; }

.question { background: var(--color-accent-subtle); border-radius: var(--radius-sm); padding: var(--space-3) var(--space-4); }
.question p { font-size: var(--text-sm); color: var(--color-text-primary); margin: 0; }

.result-actions { display: flex; gap: var(--space-3); }

.btn { display: inline-flex; align-items: center; justify-content: center; height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-base); font-weight: 600; font-family: var(--font-family); border: none; cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover:not(:disabled) { background-color: var(--color-accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: var(--color-surface); color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-secondary:hover { border-color: var(--color-accent); color: var(--color-accent); }
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { border-color: var(--color-text-tertiary); }
</style>
