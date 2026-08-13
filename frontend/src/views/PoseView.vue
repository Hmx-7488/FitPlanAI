<script setup lang="ts">
defineOptions({ name: 'PoseView' })
import { ref, nextTick, onActivated, onUnmounted, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { analyzePose, analyzePoseVideo, deletePoseAnalysis } from '../api'
import type { PoseAnalysis } from '../types'
import {
  analyzePoseImage as extractImagePose,
  analyzePoseVideo as extractVideoPose,
} from '../services/poseLandmarker'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const deleting = ref(false)
const analysisStage = ref('')
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

// keep-alive reactivation：重新播放结果动画
onActivated(() => {
  if (result.value) animateResult()
})

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
  if (previewUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(previewUrl.value)
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
    if (selectedFile.value.type.startsWith('video/')) {
      analysisStage.value = '正在逐帧提取人体关键点...'
      const { frames, payload } = await extractVideoPose(selectedFile.value)
      if (frames.length < 2) {
        throw new Error('视频抽帧失败，请换一个更清晰的视频')
      }
      analysisStage.value = '正在计算关节角度、轨迹和速度...'
      const res = await analyzePoseVideo(
        Number(userId),
        selectedFile.value,
        frames,
        selectedMovement.value,
        payload,
      )
      result.value = res
    } else {
      analysisStage.value = '正在检测人体关键点...'
      const payload = await extractImagePose(selectedFile.value)
      const res = await analyzePose(Number(userId), selectedFile.value, selectedMovement.value, payload)
      result.value = res
    }
    riskWarnings.value = result.value?.risk_warnings || []
    if (result.value?.analysis_status === 'rejected') {
      ElMessage.warning('拍摄质量不足，请按提示重新拍摄')
    } else if (result.value?.analysis_source === 'template') {
      ElMessage.warning('检测服务失败，当前仅显示模板参考')
    } else {
      ElMessage.success('分析完成')
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '分析失败')
  } finally {
    loading.value = false
    analysisStage.value = ''
  }
}

function reset() {
  if (previewUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(previewUrl.value)
  }
  selectedFile.value = null
  previewUrl.value = ''
  result.value = null
  riskWarnings.value = []
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
}

async function deleteCurrentAnalysis() {
  const analysisId = result.value?.analysis_id
  const userId = Number(localStorage.getItem('userId'))
  if (!analysisId || !Number.isInteger(userId) || userId <= 0) return
  try {
    await ElMessageBox.confirm(
      '这会删除本次动作分析记录及上传的图片或视频，且无法恢复。',
      '删除动作分析',
      { confirmButtonText: '确认删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  deleting.value = true
  try {
    await deletePoseAnalysis(userId, analysisId)
    reset()
    ElMessage.success('动作分析及媒体已删除')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '删除失败，请稍后重试')
  } finally {
    deleting.value = false
  }
}

onUnmounted(() => {
  if (previewUrl.value.startsWith('blob:')) {
    URL.revokeObjectURL(previewUrl.value)
  }
})

function severityColor(severity: string): string {
  if (severity === 'high') return 'var(--color-danger)'
  if (severity === 'medium') return 'var(--color-warning)'
  return 'var(--color-text-secondary)'
}

function riskLevelLabel(level: string): string {
  if (level === 'high') return '高风险'
  if (level === 'medium') return '中风险'
  return '低风险'
}

function riskLevelColor(level: string): string {
  if (level === 'high') return 'var(--color-danger)'
  if (level === 'medium') return 'var(--color-warning)'
  return 'oklch(0.55 0.14 145)'
}

function metricColor(score: number): string {
  if (score >= 80) return 'oklch(0.55 0.14 145)'
  if (score >= 60) return 'var(--color-warning)'
  return 'var(--color-danger)'
}

function sourceLabel(source?: PoseAnalysis['analysis_source']) {
  if (source === 'hybrid') return '关键点量化 + AI 解读'
  if (source === 'keypoint_only') return '仅关键点量化'
  if (source === 'vision_only') return '仅视觉估算'
  if (source === 'template') return '模板参考'
  if (source === 'rejected') return '质量未通过'
  return '分析结果'
}

const jointLabels: Record<string, string> = {
  left_knee: '左膝',
  right_knee: '右膝',
  left_hip: '左髋',
  right_hip: '右髋',
  left_elbow: '左肘',
  right_elbow: '右肘',
  left_shoulder: '左肩',
  right_shoulder: '右肩',
}
</script>

<template>
  <div class="pose-page" ref="pageRef">
    <div class="page-header">
      <h1>AI 动作分析</h1>
      <p>MediaPipe 逐帧计算关节角度、轨迹和速度，AI 负责解释动作问题与纠正建议。</p>
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
          <span class="upload-hint">视频建议 5-30 秒，固定机位拍摄，全身与手脚持续入镜</span>
        </div>
      </div>
      <input ref="fileInputRef" type="file" accept="image/*,video/*" style="display:none" @change="onFileChange" />
      <div class="upload-actions">
        <button class="btn btn-primary" :disabled="!selectedFile || loading" @click="doAnalyze">
          {{ loading ? (analysisStage || '分析中...') : '开始分析' }}
        </button>
      </div>
    </div>

    <!-- Result -->
    <div v-if="result" class="result-section">
      <div class="result-header">
        <h2>{{ result.movement_name }} 分析结果</h2>
        <span
          class="source-badge"
          :class="`source-badge--${result.analysis_source || 'vision_only'}`"
        >{{ sourceLabel(result.analysis_source) }}</span>
        <span class="risk-badge" :style="{ color: riskLevelColor(result.risk_level), borderColor: riskLevelColor(result.risk_level) }">
          {{ riskLevelLabel(result.risk_level) }}
        </span>
      </div>

      <div class="photo-preview" v-if="result.video_url">
        <video :src="result.video_url" controls playsinline></video>
      </div>
      <div class="photo-preview" v-else-if="result.photo_url">
        <img :src="result.photo_url" alt="动作照片" />
      </div>

      <div v-if="result.analysis_source === 'template'" class="fallback-notice">
        本次没有获得有效关键点或视觉分析结果。下方内容是通用动作模板，不代表系统检测到了这些问题。
      </div>

      <div v-if="result.analysis_status === 'rejected'" class="quality-rejection">
        <h3>拍摄质量未通过</h3>
        <p>{{ result.summary }}</p>
        <ul>
          <li v-for="issue in result.pose_quality?.issues" :key="issue">{{ issue }}</li>
        </ul>
        <p>请固定相机、保持全身和手脚入镜，避免遮挡，并从能看清主要关节运动的侧面或正面重拍。</p>
      </div>

      <!-- Score -->
      <div v-else class="score-card">
        <div class="score-value">{{ result.overall_score }}</div>
        <div class="score-label">动作评分（满分 100）</div>
        <p v-if="result.summary" class="score-summary">{{ result.summary }}</p>
        <div class="score-meta-row">
          <span v-if="result.confidence != null" class="score-meta-item">
            置信度 {{ Math.round(result.confidence * 100) }}%
          </span>
          <span v-if="result.media_type === 'video' && result.rep_count_estimate" class="score-meta-item">
            约 {{ result.rep_count_estimate }} 次动作
          </span>
          <span v-if="result.analyzed_frames" class="score-meta-item">
            分析 {{ result.analyzed_frames }} 帧
          </span>
          <span v-if="result.pose_quality" class="score-meta-item">
            有效帧 {{ Math.round(result.pose_quality.usable_frame_ratio * 100) }}%
          </span>
        </div>
        <div class="score-bar-track">
          <div class="score-bar-fill" :style="{ width: result.overall_score + '%' }"></div>
        </div>
      </div>

      <div class="card" v-if="result.analysis_status !== 'rejected' && Object.keys(result.joint_angles || {}).length">
        <h3>关节角度范围</h3>
        <div class="angle-grid">
          <div v-for="(angle, joint) in result.joint_angles" :key="joint" class="angle-item">
            <span>{{ jointLabels[String(joint)] || joint }}</span>
            <b>{{ angle.min }}° - {{ angle.max }}°</b>
            <small>变化 {{ angle.range }}°</small>
          </div>
        </div>
      </div>

      <!-- Metrics -->
      <div class="card" v-if="result.analysis_status !== 'rejected' && result.metrics?.length">
        <h3>维度评分</h3>
        <div class="metrics-grid">
          <div v-for="m in result.metrics" :key="m.name" class="metric-item">
            <div class="metric-header">
              <span class="metric-name">{{ m.name }}</span>
              <span v-if="m.source === 'keypoints'" class="metric-source">实测</span>
              <span class="metric-score" :style="{ color: metricColor(m.score) }">{{ m.score }}</span>
            </div>
            <div class="metric-bar-track">
              <div class="metric-bar-fill" :style="{ width: m.score + '%', background: metricColor(m.score) }"></div>
            </div>
            <p class="metric-desc">{{ m.description }}</p>
          </div>
        </div>
      </div>

      <!-- Good points -->
      <div class="card card--good" v-if="result.analysis_status !== 'rejected' && result.good_points?.length">
        <h3>✅ 做得好的方面</h3>
        <div class="good-points">
          <span v-for="p in result.good_points" :key="p" class="good-tag">{{ p }}</span>
        </div>
      </div>

      <!-- Video phases -->
      <div class="card" v-if="result.analysis_status !== 'rejected' && result.phases?.length">
        <h3>视频阶段观察</h3>
        <div v-for="phase in result.phases" :key="phase.phase + phase.observation" class="phase-item">
          <span class="phase-name">{{ phase.phase }}</span>
          <p>{{ phase.observation }}</p>
        </div>
      </div>

      <!-- Issues -->
      <div class="card" v-if="result.analysis_status !== 'rejected' && result.issues.length">
        <h3>问题项</h3>
        <div v-for="(issue, i) in result.issues" :key="i" class="issue-item">
          <div class="issue-top">
            <span class="issue-title">{{ issue.title }}</span>
            <span class="issue-severity" :style="{ color: severityColor(issue.severity) }">
              {{ issue.severity === 'high' ? '⚠️ 严重' : issue.severity === 'medium' ? '⚡ 中等' : '💡 轻微' }}
            </span>
            <span v-if="issue.timestamp != null" class="issue-timestamp">{{ issue.timestamp }}s</span>
          </div>
          <p class="issue-desc">{{ issue.description }}</p>
          <p v-if="issue.impact" class="issue-impact">影响：{{ issue.impact }}</p>
          <p class="issue-correction">💡 {{ issue.correction }}</p>
        </div>
      </div>

      <!-- Corrections -->
      <div class="card card--corrections" v-if="result.analysis_status !== 'rejected' && result.corrections?.length">
        <h3>🎯 纠正训练建议</h3>
        <div v-for="(c, i) in result.corrections" :key="i" class="correction-item">
          <div class="correction-area">{{ c.area }}</div>
          <p class="correction-technique">{{ c.technique }}</p>
          <div v-if="c.drills?.length" class="correction-drills">
            <span v-for="d in c.drills" :key="d" class="drill-tag">{{ d }}</span>
          </div>
          <div class="correction-meta">
            <span v-if="c.sets_reps" class="correction-sets">📋 {{ c.sets_reps }}</span>
            <span v-if="c.next_filming_tip" class="correction-tip">🎬 {{ c.next_filming_tip }}</span>
          </div>
        </div>
      </div>

      <!-- Coach cues -->
      <div class="card card--accent" v-if="result.analysis_status !== 'rejected' && result.coach_cues.length">
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
        <button class="btn btn-danger" :disabled="deleting" @click="deleteCurrentAnalysis">
          {{ deleting ? '删除中...' : '删除记录与媒体' }}
        </button>
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
.source-badge { font-size: var(--text-xs); font-weight: 700; padding: 3px 8px; border-radius: var(--radius-sm); }
.source-badge--hybrid { background: oklch(0.93 0.06 145); color: oklch(0.40 0.12 145); }
.source-badge--keypoint_only { background: oklch(0.93 0.04 230); color: oklch(0.42 0.12 230); }
.source-badge--vision_only { background: oklch(0.94 0.04 250); color: oklch(0.43 0.10 250); }
.source-badge--template, .source-badge--rejected { background: oklch(0.94 0.05 80); color: oklch(0.45 0.12 80); }
.risk-badge { font-size: var(--text-xs); font-weight: 700; padding: 2px 10px; border: 1.5px solid; border-radius: var(--radius-sm); background: transparent; }
.fallback-notice, .quality-rejection { padding: var(--space-4); border: 1px solid oklch(0.86 0.08 75); border-radius: var(--radius-md); background: oklch(0.96 0.04 80); color: var(--color-text-primary); line-height: var(--leading-relaxed); }
.quality-rejection h3 { margin: 0 0 var(--space-2); }
.quality-rejection p { margin: var(--space-2) 0; }

.photo-preview img,
.photo-preview video { max-width: 100%; max-height: 360px; border-radius: var(--radius-sm); }

.score-card { text-align: center; background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-6); }
.score-value { font-family: var(--font-mono); font-size: 56px; font-weight: 800; color: var(--color-accent); line-height: 1; }
.score-label { font-size: var(--text-sm); color: var(--color-text-tertiary); margin-top: var(--space-2); margin-bottom: var(--space-4); }
.score-bar-track { height: 6px; background: var(--color-border-subtle); border-radius: 3px; overflow: hidden; }
.score-bar-fill { height: 100%; background: var(--color-accent); border-radius: 3px; transition: width var(--duration-normal) var(--ease-out); }
.score-summary { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); margin-top: var(--space-3); margin-bottom: var(--space-2); }
.score-meta-row { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--space-3); margin-top: var(--space-2); margin-bottom: var(--space-3); }
.score-meta-item { font-size: var(--text-xs); color: var(--color-text-tertiary); }

.card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.card h3 { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-3); }
.card--accent { background: var(--color-accent-subtle); border-color: oklch(0.90 0.03 145); }
.card--warn { background: oklch(0.95 0.04 80); border-color: oklch(0.90 0.06 80); }
.card--good { background: oklch(0.96 0.03 145); border-color: oklch(0.90 0.04 145); }
.card--corrections { background: oklch(0.96 0.02 250); border-color: oklch(0.90 0.03 250); }

/* Metrics */
.metrics-grid { display: flex; flex-direction: column; gap: var(--space-4); }
.metric-item { display: flex; flex-direction: column; gap: var(--space-1); }
.metric-header { display: flex; justify-content: space-between; align-items: baseline; }
.metric-name { font-size: var(--text-sm); font-weight: 600; color: var(--color-text-primary); }
.metric-source { margin-left: auto; margin-right: var(--space-2); padding: 1px 5px; border-radius: 3px; background: var(--color-accent-subtle); color: var(--color-accent); font-size: 10px; font-weight: 700; }
.metric-score { font-size: var(--text-lg); font-weight: 800; font-family: var(--font-mono); }
.metric-bar-track { height: 5px; background: var(--color-border-subtle); border-radius: 3px; overflow: hidden; }
.metric-bar-fill { height: 100%; border-radius: 3px; transition: width var(--duration-normal) var(--ease-out); }
.metric-desc { font-size: var(--text-xs); color: var(--color-text-tertiary); margin: 0; }

/* Good points */
.good-points { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.good-tag { font-size: var(--text-sm); font-weight: 600; padding: 4px 12px; background: oklch(0.92 0.06 145); color: oklch(0.38 0.12 145); border-radius: var(--radius-sm); }

.issue-item { padding: var(--space-3) 0; border-bottom: 1px solid var(--color-border-subtle); }
.issue-item:last-child { border-bottom: none; padding-bottom: 0; }
.issue-top { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-1); flex-wrap: wrap; }
.issue-title { font-size: var(--text-base); font-weight: 700; color: var(--color-text-primary); }
.issue-severity { font-size: var(--text-xs); font-weight: 600; }
.issue-timestamp { font-size: var(--text-xs); color: var(--color-text-tertiary); font-family: var(--font-mono); padding: 1px 6px; background: var(--color-border-subtle); border-radius: var(--radius-sm); }
.issue-desc { font-size: var(--text-sm); color: var(--color-text-primary); margin-bottom: var(--space-1); }
.issue-impact { font-size: var(--text-xs); color: var(--color-text-tertiary); margin-bottom: var(--space-1); }
.issue-correction { font-size: var(--text-sm); color: var(--color-accent); }

/* Corrections */
.correction-item { padding: var(--space-3) 0; border-bottom: 1px solid oklch(0.92 0.01 250); }
.correction-item:last-child { border-bottom: none; padding-bottom: 0; }
.correction-area { font-size: var(--text-sm); font-weight: 700; color: var(--color-text-primary); margin-bottom: var(--space-1); }
.correction-technique { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); margin-bottom: var(--space-2); }
.correction-drills { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-2); }
.drill-tag { font-size: var(--text-xs); font-weight: 600; padding: 3px 10px; background: oklch(0.92 0.04 250); color: oklch(0.40 0.10 250); border-radius: var(--radius-sm); }
.correction-meta { display: flex; flex-wrap: wrap; gap: var(--space-3); }
.correction-sets, .correction-tip { font-size: var(--text-xs); color: var(--color-text-tertiary); }

.phase-item { padding: var(--space-3) 0; border-bottom: 1px solid var(--color-border-subtle); }
.phase-item:last-child { border-bottom: none; padding-bottom: 0; }
.phase-name { display: inline-block; font-size: var(--text-xs); font-weight: 700; color: var(--color-accent); margin-bottom: var(--space-1); }
.phase-item p { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); }

.cues { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.cue-tag { font-size: var(--text-sm); font-weight: 600; padding: 4px 12px; background: var(--color-accent-subtle); color: var(--color-accent); border-radius: var(--radius-sm); }

.risk-text { font-size: var(--text-base); color: var(--color-text-primary); margin-bottom: var(--space-2); }
.angle-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-2); }
.angle-item { display: grid; gap: 3px; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); }
.angle-item span, .angle-item small { color: var(--color-text-tertiary); font-size: var(--text-xs); }
.angle-item b { font-family: var(--font-mono); }

.result-actions { display: flex; gap: var(--space-3); }

.btn { display: inline-flex; align-items: center; justify-content: center; height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font-size: var(--text-base); font-weight: 600; font-family: var(--font-family); border: none; cursor: pointer; transition: all var(--duration-fast) var(--ease-out); }
.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover:not(:disabled) { background-color: var(--color-accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { border-color: var(--color-text-tertiary); }
.btn-danger { background: transparent; color: var(--color-danger); border: 1px solid color-mix(in srgb, var(--color-danger) 45%, transparent); }
.btn-danger:hover:not(:disabled) { background: color-mix(in srgb, var(--color-danger) 8%, transparent); }
.btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }

@media (max-width: 640px) {
  .result-header { align-items: flex-start; flex-wrap: wrap; }
  .angle-grid { grid-template-columns: 1fr; }
  .result-actions { flex-direction: column; }
}
</style>
