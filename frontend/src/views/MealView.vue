<script setup lang="ts">
import { ref, computed, nextTick, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import type { MealAnalysis } from '../types'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const mealType = ref('lunch')
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')

// 每个餐食类型独立保存状态
interface MealState {
  selectedFile: File | null
  previewUrl: string
  result: MealAnalysis | null
}

const mealStates = ref<Record<string, MealState>>({
  breakfast: { selectedFile: null, previewUrl: '', result: null },
  lunch: { selectedFile: null, previewUrl: '', result: null },
  dinner: { selectedFile: null, previewUrl: '', result: null },
  snack: { selectedFile: null, previewUrl: '', result: null },
})

// 计算当前选中餐食类型的状态
const currentState = computed(() => mealStates.value[mealType.value])
const selectedFile = computed(() => currentState.value.selectedFile)
const previewUrl = computed(() => currentState.value.previewUrl)
const result = computed(() => currentState.value.result)

function animateResult() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.result-header, .photo-preview'), { y: 20, opacity: 0, duration: 0.4 })
    tl.from(pageRef.value.querySelectorAll('.total-card'), { y: 30, opacity: 0, scale: 0.95, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.summary-card'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.items-card'), { y: 20, opacity: 0, duration: 0.4 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.question'), { y: 15, opacity: 0, duration: 0.3 }, '-=0.1')
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

async function doAnalyze() {
  if (!currentState.value.selectedFile) return
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  loading.value = true
  try {
    const formData = new FormData()
    formData.append('user_id', userId)
    formData.append('meal_type', mealType.value)
    formData.append('image', currentState.value.selectedFile)
    const res = await axios.post('/api/meal/analyze', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
    mealStates.value[mealType.value].result = res.data
    ElMessage.success('识别完成')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '识别失败')
  } finally {
    loading.value = false
  }
}

function resetCurrentMeal() {
  mealStates.value[mealType.value] = {
    selectedFile: null,
    previewUrl: '',
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

    <!-- Upload -->
    <div v-if="!result" class="upload-section">
      <div class="meal-type-select">
        <label class="field-label">餐次</label>
        <div class="radio-group">
          <button
            v-for="opt in mealTypeOptions"
            :key="opt.value"
            class="radio-btn"
            :class="{ 'radio-btn--active': mealType === opt.value }"
            @click="mealType = opt.value"
          >{{ opt.label }}</button>
        </div>
      </div>

      <div class="upload-area" @click="fileInputRef?.click()">
        <div v-if="previewUrl" class="preview">
          <img :src="previewUrl" alt="预览" />
        </div>
        <div v-else class="upload-placeholder">
          <span class="upload-icon">&#127860;</span>
          <p>点击上传餐食照片</p>
          <span class="upload-hint">拍摄你正在吃或已吃的食物</span>
        </div>
      </div>
      <input ref="fileInputRef" type="file" accept="image/*" style="display:none" @change="onFileChange" />
      <div class="upload-actions">
        <button class="btn btn-primary" :disabled="!selectedFile || loading" @click="doAnalyze">
          {{ loading ? '识别中...' : '开始识别' }}
        </button>
      </div>
    </div>

    <!-- Result -->
    <div v-if="result" class="result-section">
      <div class="result-header">
        <h2>{{ mealTypeOptions.find(o => o.value === mealType)?.label || '餐食' }}识别结果</h2>
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
          <span class="item-confidence" v-if="item.confidence < 1">{{ (item.confidence * 100).toFixed(0) }}%</span>
        </div>
      </div>

      <!-- Question -->
      <div class="question" v-if="result.question_to_user">
        <p>{{ result.question_to_user }}</p>
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

.meal-type-select { margin-bottom: var(--space-5); }
.field-label { display: block; font-size: var(--text-sm); font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-2); }
.radio-group { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.radio-btn { height: 40px; padding: 0 var(--space-4); border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); font-size: var(--text-base); font-family: var(--font-family); color: var(--color-text-secondary); cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.radio-btn:hover { border-color: var(--color-accent); color: var(--color-text-primary); }
.radio-btn--active { border-color: var(--color-accent); background: var(--color-accent-subtle); color: var(--color-accent); font-weight: 600; }

.upload-section { text-align: center; }
.upload-area { border: 2px dashed var(--color-border); border-radius: var(--radius-md); padding: var(--space-10); cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out); margin-bottom: var(--space-5); }
.upload-area:hover { border-color: var(--color-accent); }
.upload-placeholder { color: var(--color-text-tertiary); }
.upload-icon { font-size: 48px; display: block; margin-bottom: var(--space-3); opacity: 0.4; }
.upload-hint { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.preview img { max-width: 100%; max-height: 300px; border-radius: var(--radius-sm); }
.upload-actions { display: flex; justify-content: center; gap: var(--space-3); }

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
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { border-color: var(--color-text-tertiary); }
</style>
