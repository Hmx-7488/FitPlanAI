<script setup lang="ts">
defineOptions({ name: 'PoseView' })
import { ref, nextTick, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { analyzePose, analyzePoseVideo } from '../api'
import type { PoseAnalysis } from '../types'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const selectedFile = ref<File | null>(null)
const previewUrl = ref('')
const result = ref<PoseAnalysis | null>(null)
const riskWarnings = ref<string[]>([])
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')

function animateResult() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.result-header'), { y: 20, opacity: 0, duration: 0.4 })
    tl.from(pageRef.value.querySelectorAll('.photo-preview'), { y: 20, opacity: 0, scale: 0.97, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.score-card'), { y: 30, opacity: 0, scale: 0.95, duration: 0.6 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.card'), { y: 25, opacity: 0, stagger: 0.1, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.result-actions'), { y: 15, opacity: 0, duration: 0.3 }, '-=0.1')
    // 评分数字滚动
    const scoreEl = pageRef.value.querySelector('.score-value') as HTMLElement
    if (scoreEl) {
      const target = parseInt(scoreEl.textContent || '0')
      const obj = { val: 0 }
      gsap.to(obj, { val: target, duration: 1, ease: 'power2.out', delay: 0.4, onUpdate() { scoreEl.textContent = Math.round(obj.val).toString() } })
    }
    // 评分条动画
    const barFill = pageRef.value.querySelector('.score-bar-fill') as HTMLElement
    if (barFill) {
      const targetWidth = barFill.style.width
      gsap.fromTo(barFill, { width: '0%' }, { width: targetWidth, duration: 1, ease: 'power2.out', delay: 0.5 })
    }
  })
}

watch(result, (val) => { if (val) animateResult() })

const movementOptions = [
  { value: 'squat', label: '深蹲' },
  { value: 'deadlift', label: '硬拉' },
  { value: 'bench_press', label: '卧推' },
  { value: 'pull_up', label: '引体向上' },
  { value: 'push_up', label: '俯卧撑' },
]
const selectedMovement = ref('squat')

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/') && !file.type.startsWith('video/')) {
    ElMessage.warning('请选择图片或视频文件')
    return
  }
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
}

function waitForEvent(target: EventTarget, eventName: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup()
      reject(new Error(`等待 ${eventName} 超时`))
    }, 10000)
    const cleanup = () => {
      window.clearTimeout(timeout)
      target.removeEventListener(eventName, onDone)
      target.removeEventListener('error', onError)
    }
    const onDone = () => {
      cleanup()
      resolve()
    }
    const onError = () => {
      cleanup()
      reject(new Error('视频加载失败'))
    }
    target.addEventListener(eventName, onDone, { once: true })
    target.addEventListener('error', onError, { once: true })
  })
}

async function extractVideoFrames(file: File, frameCount = 5): Promise<File[]> {
  const video = document.createElement('video')
  video.preload = 'metadata'
  video.muted = true
  video.playsInline = true
  video.src = URL.createObjectURL(file)

  try {
    await waitForEvent(video, 'loadedmetadata')
    const duration = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : 1
    const canvas = document.createElement('canvas')
    const width = Math.min(video.videoWidth || 720, 960)
    const height = Math.max(1, Math.round(width * ((video.videoHeight || 540) / (video.videoWidth || 720))))
    canvas.width = width
    canvas.height = height
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('无法创建抽帧画布')

    const frames: File[] = []
    const points = Array.from({ length: frameCount }, (_, i) => (i + 1) / (frameCount + 1))
    for (const pct of points) {
      video.currentTime = Math.min(duration * pct, Math.max(duration - 0.05, 0))
      await waitForEvent(video, 'seeked')
      ctx.drawImage(video, 0, 0, width, height)
      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.82))
      if (blob) {
        frames.push(new File([blob], `pose_frame_${frames.length}.jpg`, { type: 'image/jpeg' }))
      }
    }
    return frames
  } finally {
    URL.revokeObjectURL(video.src)
  }
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
    if (selectedFile.value.type.startsWith('video/')) {
      const frames = await extractVideoFrames(selectedFile.value)
      if (frames.length < 2) {
        throw new Error('视频抽帧失败，请换一个更清晰的视频')
      }
      const res = await analyzePoseVideo(Number(userId), selectedFile.value, frames, selectedMovement.value)
      result.value = res
    } else {
      const res = await analyzePose(Number(userId), selectedFile.value, selectedMovement.value)
      result.value = res
    }
    riskWarnings.value = result.value?.risk_warnings || []
    ElMessage.success('分析完成')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '分析失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  selectedFile.value = null
  previewUrl.value = ''
  result.value = null
  riskWarnings.value = []
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
}

function severityColor(severity: string): string {
  if (severity === 'high') return 'var(--color-danger)'
  if (severity === 'medium') return 'var(--color-warning)'
  return 'var(--color-text-secondary)'
}
</script>

<template>
  <div class="pose-page" ref="pageRef">
    <div class="page-header">
      <h1>AI 动作分析</h1>
      <p>上传训练动作照片或视频，AI 评估动作质量并给出纠正建议。</p>
    </div>

    <!-- Upload -->
    <div v-if="!result" class="upload-section">
      <div class="movement-select">
        <label class="field-label">选择动作</label>
        <div class="radio-group">
          <button
            v-for="opt in movementOptions"
            :key="opt.value"
            class="radio-btn"
            :class="{ 'radio-btn--active': selectedMovement === opt.value }"
            @click="selectedMovement = opt.value"
          >{{ opt.label }}</button>
        </div>
      </div>

      <div class="upload-area" @click="fileInputRef?.click()">
        <div v-if="previewUrl" class="preview">
          <video
            v-if="selectedFile?.type.startsWith('video/')"
            :src="previewUrl"
            controls
            muted
            playsinline
          ></video>
          <img v-else :src="previewUrl" alt="预览" />
        </div>
        <div v-else class="upload-placeholder">
          <span class="upload-icon">&#127947;</span>
          <p>点击上传动作照片或视频</p>
          <span class="upload-hint">视频建议 5-30 秒，侧面或正面拍摄，全身入镜</span>
        </div>
      </div>
      <input ref="fileInputRef" type="file" accept="image/*,video/*" style="display:none" @change="onFileChange" />
      <div class="upload-actions">
        <button class="btn btn-primary" :disabled="!selectedFile || loading" @click="doAnalyze">
          {{ loading ? '分析中...' : '开始分析' }}
        </button>
      </div>
    </div>

    <!-- Result -->
    <div v-if="result" class="result-section">
      <div class="result-header">
        <h2>{{ result.movement_name }} 分析结果</h2>
        <span class="ai-badge" v-if="result.is_ai_analysis">AI 视觉分析</span>
        <span class="mock-badge" v-else>模板分析</span>
      </div>

      <div class="photo-preview" v-if="result.video_url">
        <video :src="result.video_url" controls playsinline></video>
      </div>
      <div class="photo-preview" v-else-if="result.photo_url">
        <img :src="result.photo_url" alt="动作照片" />
      </div>

      <!-- Score -->
      <div class="score-card">
        <div class="score-value">{{ result.score }}</div>
        <div class="score-label">动作评分（满分 100）</div>
        <div class="score-meta" v-if="result.media_type === 'video' && result.rep_count_estimate">
          识别到约 {{ result.rep_count_estimate }} 次动作
        </div>
        <div class="score-bar-track">
          <div class="score-bar-fill" :style="{ width: result.score + '%' }"></div>
        </div>
      </div>

      <!-- Video phases -->
      <div class="card" v-if="result.phases?.length">
        <h3>视频阶段观察</h3>
        <div v-for="phase in result.phases" :key="phase.phase + phase.observation" class="phase-item">
          <span class="phase-name">{{ phase.phase }}</span>
          <p>{{ phase.observation }}</p>
        </div>
      </div>

      <!-- Issues -->
      <div class="card" v-if="result.issues.length">
        <h3>问题项</h3>
        <div v-for="(issue, i) in result.issues" :key="i" class="issue-item">
          <div class="issue-severity" :style="{ color: severityColor(issue.severity) }">
            {{ issue.severity === 'high' ? '⚠️ 严重' : issue.severity === 'medium' ? '⚡ 中等' : '💡 轻微' }}
          </div>
          <p class="issue-desc">{{ issue.description }}</p>
          <p class="issue-suggestion">💡 {{ issue.suggestion }}</p>
        </div>
      </div>

      <!-- Coach cues -->
      <div class="card card--accent">
        <h3>教练提示</h3>
        <div class="cues">
          <span v-for="cue in result.coach_cues" :key="cue" class="cue-tag">{{ cue }}</span>
        </div>
      </div>

      <!-- Risk warnings -->
      <div v-if="riskWarnings.length" class="card card--warn">
        <h3>健康风险提示</h3>
        <p v-for="w in riskWarnings" :key="w" class="risk-text">{{ w }}</p>
      </div>

      <div class="result-actions">
        <button class="btn btn-primary" @click="reset">重新分析</button>
        <button class="btn btn-ghost" @click="router.push('/plan')">查看计划</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pose-page { max-width: 640px; margin: 0 auto; }
.page-header { margin-bottom: var(--space-8); }
.page-header h1 { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); margin-bottom: var(--space-2); }
.page-header p { font-size: var(--text-md); color: var(--color-text-secondary); }
.note { font-size: var(--text-sm); color: var(--color-text-tertiary); }

.movement-select { margin-bottom: var(--space-5); }
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
.preview img,
.preview video { max-width: 100%; max-height: 320px; border-radius: var(--radius-sm); }
.upload-actions { display: flex; justify-content: center; gap: var(--space-3); }

.result-section { display: flex; flex-direction: column; gap: var(--space-4); }
.result-header { display: flex; align-items: center; gap: var(--space-3); }
.result-header h2 { font-size: var(--text-xl); font-weight: 700; }
.mock-badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 8px; background: oklch(0.93 0.06 80); color: oklch(0.45 0.12 80); border-radius: var(--radius-sm); }
.ai-badge { font-size: var(--text-xs); font-weight: 600; padding: 2px 8px; background: oklch(0.93 0.06 145); color: oklch(0.40 0.12 145); border-radius: var(--radius-sm); }

.photo-preview img,
.photo-preview video { max-width: 100%; max-height: 360px; border-radius: var(--radius-sm); }

.score-card { text-align: center; background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-6); }
.score-value { font-family: var(--font-mono); font-size: 56px; font-weight: 800; color: var(--color-accent); line-height: 1; }
.score-label { font-size: var(--text-sm); color: var(--color-text-tertiary); margin-top: var(--space-2); margin-bottom: var(--space-4); }
.score-meta { font-size: var(--text-sm); color: var(--color-text-secondary); margin-top: calc(-1 * var(--space-2)); margin-bottom: var(--space-3); }
.score-bar-track { height: 6px; background: var(--color-border-subtle); border-radius: 3px; overflow: hidden; }
.score-bar-fill { height: 100%; background: var(--color-accent); border-radius: 3px; transition: width var(--duration-normal) var(--ease-out); }

.card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.card h3 { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-3); }
.card--accent { background: var(--color-accent-subtle); border-color: oklch(0.90 0.03 145); }
.card--warn { background: oklch(0.95 0.04 80); border-color: oklch(0.90 0.06 80); }

.issue-item { padding: var(--space-3) 0; border-bottom: 1px solid var(--color-border-subtle); }
.issue-item:last-child { border-bottom: none; padding-bottom: 0; }
.issue-severity { font-size: var(--text-sm); font-weight: 600; margin-bottom: var(--space-1); }
.issue-desc { font-size: var(--text-base); color: var(--color-text-primary); margin-bottom: var(--space-1); }
.issue-suggestion { font-size: var(--text-sm); color: var(--color-text-secondary); }

.phase-item { padding: var(--space-3) 0; border-bottom: 1px solid var(--color-border-subtle); }
.phase-item:last-child { border-bottom: none; padding-bottom: 0; }
.phase-name { display: inline-block; font-size: var(--text-xs); font-weight: 700; color: var(--color-accent); margin-bottom: var(--space-1); }
.phase-item p { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); }

.cues { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.cue-tag { font-size: var(--text-sm); font-weight: 600; padding: 4px 12px; background: var(--color-accent-subtle); color: var(--color-accent); border-radius: var(--radius-sm); }

.risk-text { font-size: var(--text-base); color: var(--color-text-primary); margin-bottom: var(--space-2); }

.result-actions { display: flex; gap: var(--space-3); }

.btn { display: inline-flex; align-items: center; justify-content: center; height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-base); font-weight: 600; font-family: var(--font-family); border: none; cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover:not(:disabled) { background-color: var(--color-accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { border-color: var(--color-text-tertiary); }
</style>
