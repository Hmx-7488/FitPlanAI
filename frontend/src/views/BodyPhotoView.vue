<script setup lang="ts">
import { ref, nextTick, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import type { BodyPhotoAnalysis } from '../types'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const selectedFile = ref<File | null>(null)
const previewUrl = ref('')
const result = ref<BodyPhotoAnalysis | null>(null)
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')

function animateResult() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.result-header'), { y: 20, opacity: 0, duration: 0.4 })
    tl.from(pageRef.value.querySelectorAll('.photo-preview'), { y: 20, opacity: 0, scale: 0.97, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.card'), { y: 25, opacity: 0, stagger: 0.1, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.result-actions'), { y: 15, opacity: 0, duration: 0.3 }, '-=0.1')
  })
}

watch(result, (val) => { if (val) animateResult() })

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
}

async function doAnalyze() {
  if (!selectedFile.value) return
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
    formData.append('image', selectedFile.value)
    const res = await axios.post('/api/body/analyze', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    result.value = res.data
    ElMessage.success('分析完成')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '分析失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  selectedFile.value = null
  previewUrl.value = ''
  result.value = null
}
</script>

<template>
  <div class="body-photo-page" ref="pageRef">
    <div class="page-header">
      <h1>身材照片分析</h1>
      <p>上传全身照片，AI 估算体脂率和训练重点。</p>
    </div>

    <!-- Upload -->
    <div v-if="!result" class="upload-section">
      <div class="upload-area" @click="fileInputRef?.click()">
        <div v-if="previewUrl" class="preview">
          <img :src="previewUrl" alt="预览" />
        </div>
        <div v-else class="upload-placeholder">
          <span class="upload-icon">&#128247;</span>
          <p>点击选择身材照片</p>
          <span class="upload-hint">建议全身正面照，光线充足，背景干净</span>
        </div>
      </div>
      <input ref="fileInput" type="file" accept="image/*" style="display:none" @change="onFileChange" />
      <div class="upload-actions">
        <button class="btn btn-primary" :disabled="!selectedFile || loading" @click="doAnalyze">
          {{ loading ? '分析中...' : '开始分析' }}
        </button>
      </div>
    </div>

    <!-- Result -->
    <div v-if="result" class="result-section">
      <div class="result-header">
        <h2>分析结果</h2>
        <span class="ai-badge" v-if="result.is_ai_analysis">AI 视觉分析</span>
        <span class="mock-badge" v-else>BMI 估算</span>
      </div>

      <!-- Photo -->
      <div class="photo-preview" v-if="result.photo_url">
        <img :src="result.photo_url" alt="身材照片" />
      </div>

      <!-- Body fat estimate -->
      <div class="card">
        <h3>体脂率估算</h3>
        <div class="estimate-row">
          <span class="estimate-value">{{ result.body_fat_estimate.estimated_range }}</span>
          <span class="estimate-confidence">置信度 {{ (result.body_fat_estimate.confidence * 100).toFixed(0) }}%</span>
        </div>
        <p class="estimate-note">{{ result.body_fat_estimate.note }}</p>
      </div>

      <!-- Training focus -->
      <div class="card">
        <h3>训练重点</h3>
        <div class="focus-tags">
          <span v-for="f in result.training_focus" :key="f" class="focus-tag">{{ f }}</span>
        </div>
      </div>

      <!-- Nutrition suggestion -->
      <div class="card card--accent">
        <h3>营养建议</h3>
        <p>{{ result.nutrition_suggestion }}</p>
      </div>

      <!-- Risk warnings -->
      <div v-if="(result as any).risk_warnings?.length" class="card card--warn">
        <h3>风险提示</h3>
        <p v-for="w in (result as any).risk_warnings" :key="w">{{ w }}</p>
      </div>

      <div class="result-actions">
        <button class="btn btn-primary" @click="reset">重新上传</button>
        <button class="btn btn-ghost" @click="router.push('/plan')">查看计划</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.body-photo-page { max-width: 640px; margin: 0 auto; }
.page-header { margin-bottom: var(--space-8); }
.page-header h1 { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); margin-bottom: var(--space-2); }
.page-header p { font-size: var(--text-md); color: var(--color-text-secondary); }
.note { font-size: var(--text-sm); color: var(--color-text-tertiary); }

.upload-section { text-align: center; }
.upload-area { border: 2px dashed var(--color-border); border-radius: var(--radius-md); padding: var(--space-10); cursor: pointer; transition: border-color var(--duration-fast) var(--ease-out); margin-bottom: var(--space-5); }
.upload-area:hover { border-color: var(--color-accent); }
.upload-placeholder { color: var(--color-text-tertiary); }
.upload-icon { font-size: 48px; display: block; margin-bottom: var(--space-3); opacity: 0.4; }
.upload-hint { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.preview img { max-width: 100%; max-height: 300px; border-radius: var(--radius-sm); }
.upload-actions { display: flex; justify-content: center; gap: var(--space-3); }

.result-section { display: flex; flex-direction: column; gap: var(--space-4); }
.result-header { display: flex; align-items: center; gap: var(--space-3); }
.result-header h2 { font-size: var(--text-xl); font-weight: 700; }
.mock-badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 8px; background: oklch(0.93 0.06 80); color: oklch(0.45 0.12 80); border-radius: var(--radius-sm); }
.ai-badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 8px; background: oklch(0.93 0.06 145); color: oklch(0.40 0.12 145); border-radius: var(--radius-sm); }

.photo-preview { margin-bottom: var(--space-2); }
.photo-preview img { max-width: 100%; max-height: 250px; border-radius: var(--radius-sm); }

.card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.card h3 { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-3); }
.card--accent { background: var(--color-accent-subtle); border-color: oklch(0.90 0.03 145); }
.card--warn { background: oklch(0.95 0.04 80); border-color: oklch(0.90 0.06 80); }

.estimate-row { display: flex; align-items: baseline; gap: var(--space-3); margin-bottom: var(--space-2); }
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
</style>
