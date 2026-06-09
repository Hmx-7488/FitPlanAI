<script setup lang="ts">
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { analyzeBodyPhoto } from '../api'
import type { BodyPhotoAnalysis } from '../types'
import gsap from 'gsap'

type BodyView = 'front' | 'side' | 'back'

interface BodyPhotoDraft {
  files: Partial<Record<BodyView, File>>
  previews: Partial<Record<BodyView, string>>
  result: BodyPhotoAnalysis | null
}

const draftKey = '__slimAgentBodyPhotoDraft'
const globalDraft = (window as unknown as Record<string, BodyPhotoDraft>)[draftKey] ||= {
  files: {},
  previews: {},
  result: null,
}

const router = useRouter()
const loading = ref(false)
const selectedFiles = ref<Partial<Record<BodyView, File>>>({ ...globalDraft.files })
const previewUrls = ref<Partial<Record<BodyView, string>>>({ ...globalDraft.previews })
const result = ref<BodyPhotoAnalysis | null>(globalDraft.result)
const activeView = ref<BodyView>('front')
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')

const viewOptions: { key: BodyView; label: string; hint: string }[] = [
  { key: 'front', label: '正面', hint: '自然站立，手臂略离身体' },
  { key: 'side', label: '侧面', hint: '侧身站直，腰腹轮廓清晰' },
  { key: 'back', label: '背面', hint: '背部和臀腿尽量完整入镜' },
]

const selectedCount = computed(() => Object.values(selectedFiles.value).filter(Boolean).length)
const canAnalyze = computed(() => selectedCount.value > 0 && !loading.value)

function persistDraft() {
  globalDraft.files = { ...selectedFiles.value }
  globalDraft.previews = { ...previewUrls.value }
  globalDraft.result = result.value
}

function animateResult() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.result-header'), { y: 20, opacity: 0, duration: 0.4 })
    tl.from(pageRef.value.querySelectorAll('.photo-grid'), { y: 20, opacity: 0, scale: 0.97, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.card'), { y: 25, opacity: 0, stagger: 0.1, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.result-actions'), { y: 15, opacity: 0, duration: 0.3 }, '-=0.1')
  })
}

watch(result, (val) => {
  persistDraft()
  if (val) animateResult()
})

function chooseView(view: BodyView) {
  activeView.value = view
  fileInputRef.value?.click()
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }

  const oldUrl = previewUrls.value[activeView.value]
  if (oldUrl?.startsWith('blob:')) URL.revokeObjectURL(oldUrl)

  selectedFiles.value = { ...selectedFiles.value, [activeView.value]: file }
  previewUrls.value = { ...previewUrls.value, [activeView.value]: URL.createObjectURL(file) }
  result.value = null
  persistDraft()
  input.value = ''
}

function removeView(view: BodyView) {
  const oldUrl = previewUrls.value[view]
  if (oldUrl?.startsWith('blob:')) URL.revokeObjectURL(oldUrl)

  const nextFiles = { ...selectedFiles.value }
  const nextPreviews = { ...previewUrls.value }
  delete nextFiles[view]
  delete nextPreviews[view]
  selectedFiles.value = nextFiles
  previewUrls.value = nextPreviews
  result.value = null
  persistDraft()
}

async function doAnalyze() {
  if (!canAnalyze.value) return
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  loading.value = true
  try {
    result.value = await analyzeBodyPhoto(Number(userId), {
      front: selectedFiles.value.front || null,
      side: selectedFiles.value.side || null,
      back: selectedFiles.value.back || null,
    })
    persistDraft()
    ElMessage.success('分析完成')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '分析失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.values(previewUrls.value).forEach(url => {
    if (url?.startsWith('blob:')) URL.revokeObjectURL(url)
  })
  selectedFiles.value = {}
  previewUrls.value = {}
  result.value = null
  persistDraft()
}
</script>

<template>
  <div class="body-photo-page" ref="pageRef">
    <div class="page-header">
      <h1>身材照片分析</h1>
      <p>可上传正面、侧面、背面照片，AI 会结合已提供视角估算体脂率和训练重点。</p>
    </div>

    <div v-if="!result" class="upload-section">
      <div class="view-grid">
        <button
          v-for="view in viewOptions"
          :key="view.key"
          class="view-card"
          type="button"
          @click="chooseView(view.key)"
        >
          <span class="view-label">{{ view.label }}</span>
          <span class="view-hint">{{ view.hint }}</span>
          <span v-if="previewUrls[view.key]" class="view-preview">
            <img :src="previewUrls[view.key]" :alt="view.label + '照片'" />
          </span>
          <span v-else class="view-placeholder">点击上传</span>
        </button>
      </div>

      <div class="view-actions">
        <button
          v-for="view in viewOptions"
          v-show="previewUrls[view.key]"
          :key="view.key + '-remove'"
          class="remove-view-btn"
          type="button"
          @click="removeView(view.key)"
        >
          移除{{ view.label }}
        </button>
      </div>

      <input ref="fileInputRef" type="file" accept="image/*" style="display:none" @change="onFileChange" />
      <div class="upload-actions">
        <button class="btn btn-primary" :disabled="!canAnalyze" @click="doAnalyze">
          {{ loading ? '分析中...' : `开始分析（${selectedCount}张）` }}
        </button>
      </div>
    </div>

    <div v-if="result" class="result-section">
      <div class="result-header">
        <h2>分析结果</h2>
        <span class="ai-badge" v-if="result.is_ai_analysis">AI 视觉分析</span>
        <span class="mock-badge" v-else>BMI 估算</span>
      </div>

      <div class="photo-grid">
        <div v-for="view in viewOptions" v-show="previewUrls[view.key] || result.photo_urls?.[view.key]" :key="view.key" class="photo-preview">
          <span>{{ view.label }}</span>
          <img :src="previewUrls[view.key] || result.photo_urls?.[view.key]" :alt="view.label + '照片'" />
        </div>
      </div>

      <div class="card">
        <h3>体脂率估算</h3>
        <div class="estimate-row">
          <span class="estimate-value">{{ result.body_fat_estimate.estimated_range }}</span>
          <span class="estimate-confidence">置信度 {{ (result.body_fat_estimate.confidence * 100).toFixed(0) }}%</span>
        </div>
        <p class="estimate-note">{{ result.body_fat_estimate.note }}</p>
      </div>

      <div class="card">
        <h3>训练重点</h3>
        <div class="focus-tags">
          <span v-for="f in result.training_focus" :key="f" class="focus-tag">{{ f }}</span>
        </div>
      </div>

      <div class="card card--accent">
        <h3>营养建议</h3>
        <p>{{ result.nutrition_suggestion }}</p>
      </div>

      <div class="result-actions">
        <button class="btn btn-primary" @click="reset">重新上传</button>
        <button class="btn btn-ghost" @click="router.push('/plan')">查看计划</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.body-photo-page { max-width: 760px; margin: 0 auto; }
.page-header { margin-bottom: var(--space-8); }
.page-header h1 { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); margin-bottom: var(--space-2); }
.page-header p { font-size: var(--text-md); color: var(--color-text-secondary); line-height: var(--leading-relaxed); }

.upload-section { text-align: center; }
.view-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-4); margin-bottom: var(--space-4); }
.view-card {
  min-height: 260px;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-4);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text-primary);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out), transform var(--duration-fast) var(--ease-out);
}
.view-card:hover { border-color: var(--color-accent); transform: translateY(-1px); }
.view-label { font-size: var(--text-md); font-weight: 700; }
.view-hint { min-height: 36px; font-size: var(--text-xs); color: var(--color-text-tertiary); line-height: var(--leading-normal); }
.view-preview { flex: 1; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-sm); background: var(--color-border-subtle); }
.view-preview img { width: 100%; height: 100%; object-fit: contain; display: block; }
.view-placeholder { flex: 1; display: grid; place-items: center; min-height: 150px; color: var(--color-text-tertiary); border-radius: var(--radius-sm); background: var(--color-border-subtle); }
.view-actions { min-height: 32px; display: flex; justify-content: center; gap: var(--space-2); margin-bottom: var(--space-4); }
.remove-view-btn { height: 30px; padding: 0 var(--space-3); border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: transparent; color: var(--color-text-secondary); cursor: pointer; }
.remove-view-btn:hover { border-color: var(--color-text-tertiary); color: var(--color-text-primary); }
.upload-actions { display: flex; justify-content: center; gap: var(--space-3); }

.result-section { display: flex; flex-direction: column; gap: var(--space-4); }
.result-header { display: flex; align-items: center; gap: var(--space-3); }
.result-header h2 { font-size: var(--text-xl); font-weight: 700; }
.mock-badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 8px; background: oklch(0.93 0.06 80); color: oklch(0.45 0.12 80); border-radius: var(--radius-sm); }
.ai-badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 8px; background: oklch(0.93 0.06 145); color: oklch(0.40 0.12 145); border-radius: var(--radius-sm); }
.photo-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-3); }
.photo-preview { display: flex; flex-direction: column; gap: var(--space-2); font-size: var(--text-xs); font-weight: 700; color: var(--color-text-tertiary); }
.photo-preview img { width: 100%; aspect-ratio: 3 / 4; object-fit: contain; border-radius: var(--radius-sm); background: var(--color-border-subtle); }

.card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.card h3 { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-3); }
.card--accent { background: var(--color-accent-subtle); border-color: oklch(0.90 0.03 145); }
.estimate-row { display: flex; align-items: baseline; gap: var(--space-3); margin-bottom: var(--space-2); flex-wrap: wrap; }
.estimate-value { font-family: var(--font-mono); font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); }
.estimate-confidence { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.estimate-note { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); }
.focus-tags { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.focus-tag { font-size: var(--text-sm); font-weight: 600; padding: 4px 12px; background: var(--color-accent-subtle); color: var(--color-accent); border-radius: var(--radius-sm); }
.result-actions { display: flex; gap: var(--space-3); }

.btn { display: inline-flex; align-items: center; justify-content: center; height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-base); font-weight: 600; font-family: var(--font-family); border: none; cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover:not(:disabled) { background-color: var(--color-accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { border-color: var(--color-text-tertiary); }

@media (max-width: 720px) {
  .view-grid,
  .photo-grid { grid-template-columns: 1fr; }
  .view-card { min-height: 220px; }
  .result-actions { flex-direction: column; }
}
</style>
