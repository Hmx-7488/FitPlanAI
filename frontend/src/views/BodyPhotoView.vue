<script setup lang="ts">
defineOptions({ name: 'BodyPhotoView' })

import { computed, nextTick, onActivated, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AlertTriangle, Camera, Check, History, Maximize2, RefreshCw, Trash2 } from '@lucide/vue'
import gsap from 'gsap'

import { analyzeBodyPhoto, getBodyAnalysisHistory } from '../api'
import type {
  BodyAnalysisHistoryItem,
  BodyMeasurements,
  BodyPhotoAnalysis,
} from '../types'

type BodyView = 'front' | 'side' | 'back'

interface BodyPhotoDraft {
  files: Partial<Record<BodyView, File>>
  previews: Partial<Record<BodyView, string>>
  measurements: BodyMeasurements
  result: BodyPhotoAnalysis | null
}

const draftKey = '__slimAgentBodyPhotoDraft'
const globalDraft = (window as unknown as Record<string, BodyPhotoDraft>)[draftKey] ||= {
  files: {},
  previews: {},
  measurements: {},
  result: null,
}

const router = useRouter()
const loading = ref(false)
const historyLoading = ref(false)
const selectedFiles = ref<Partial<Record<BodyView, File>>>({ ...globalDraft.files })
const previewUrls = ref<Partial<Record<BodyView, string>>>({ ...globalDraft.previews })
const measurements = ref<BodyMeasurements>({ ...globalDraft.measurements })
const result = ref<BodyPhotoAnalysis | null>(globalDraft.result)
const historyItems = ref<BodyAnalysisHistoryItem[]>([])
const activeView = ref<BodyView>('front')
const enlargedImage = ref('')
const pageRef = useTemplateRef<HTMLElement>('pageRef')
const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')

const viewOptions: { key: BodyView; label: string; hint: string }[] = [
  { key: 'front', label: '正面', hint: '自然站立，手臂略离身体，完整露出躯干和四肢' },
  { key: 'side', label: '侧面', hint: '相机与腰部同高，不收腹，保持自然呼吸' },
  { key: 'back', label: '背面', hint: '背部、臀腿完整入镜，双脚自然平行' },
]

const measurementFields: { key: keyof BodyMeasurements; label: string; unit: string; placeholder: string }[] = [
  { key: 'waist_cm', label: '腰围', unit: 'cm', placeholder: '如 82' },
  { key: 'hip_cm', label: '臀围', unit: 'cm', placeholder: '如 96' },
  { key: 'chest_cm', label: '胸围', unit: 'cm', placeholder: '如 94' },
  { key: 'neck_cm', label: '颈围', unit: 'cm', placeholder: '用于围度公式' },
  { key: 'body_fat_scale_pct', label: '体脂秤', unit: '%', placeholder: '如 21.5' },
  { key: 'measured_weight_kg', label: '本次体重', unit: 'kg', placeholder: '如 68.5' },
]

const selectedCount = computed(() => Object.values(selectedFiles.value).filter(Boolean).length)
const canAnalyze = computed(() => selectedCount.value > 0 && !loading.value)
const isRejected = computed(() => result.value?.status === 'rejected')

function persistDraft() {
  globalDraft.files = { ...selectedFiles.value }
  globalDraft.previews = { ...previewUrls.value }
  globalDraft.measurements = { ...measurements.value }
  globalDraft.result = result.value
}

function animateResult() {
  nextTick(() => {
    if (!pageRef.value) return
    gsap.from(pageRef.value.querySelectorAll('.result-block'), {
      y: 18,
      opacity: 0,
      stagger: 0.08,
      duration: 0.4,
      ease: 'power3.out',
    })
  })
}

watch([result, measurements], persistDraft, { deep: true })

onActivated(() => {
  if (result.value) animateResult()
  loadHistory()
})

onMounted(loadHistory)

async function loadHistory() {
  const userId = Number(localStorage.getItem('userId'))
  if (!userId || historyLoading.value) return
  historyLoading.value = true
  try {
    historyItems.value = await getBodyAnalysisHistory(userId, 6)
  } catch {
    historyItems.value = []
  } finally {
    historyLoading.value = false
  }
}

function chooseView(view: BodyView) {
  activeView.value = view
  fileInputRef.value?.click()
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  if (file.size > 10 * 1024 * 1024) {
    ElMessage.warning('单张图片不能超过 10MB')
    return
  }
  const oldUrl = previewUrls.value[activeView.value]
  if (oldUrl?.startsWith('blob:')) URL.revokeObjectURL(oldUrl)
  selectedFiles.value = { ...selectedFiles.value, [activeView.value]: file }
  previewUrls.value = { ...previewUrls.value, [activeView.value]: URL.createObjectURL(file) }
  result.value = null
  input.value = ''
}

function removeView(view: BodyView) {
  const oldUrl = previewUrls.value[view]
  if (oldUrl?.startsWith('blob:')) URL.revokeObjectURL(oldUrl)
  const files = { ...selectedFiles.value }
  const previews = { ...previewUrls.value }
  delete files[view]
  delete previews[view]
  selectedFiles.value = files
  previewUrls.value = previews
  result.value = null
}

async function doAnalyze() {
  if (!canAnalyze.value) return
  const userId = Number(localStorage.getItem('userId'))
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }
  loading.value = true
  try {
    result.value = await analyzeBodyPhoto(userId, {
      front: selectedFiles.value.front || null,
      side: selectedFiles.value.side || null,
      back: selectedFiles.value.back || null,
    }, measurements.value)
    if (result.value.status === 'rejected') {
      ElMessage.warning('照片未通过质量校验，请按提示重新拍摄')
    } else if (result.value.status === 'fallback') {
      ElMessage.warning('视觉服务暂不可用，已返回低置信度参考')
    } else {
      ElMessage.success('分析完成')
    }
    animateResult()
    await loadHistory()
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '分析失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  Object.values(previewUrls.value).forEach((url) => {
    if (url?.startsWith('blob:')) URL.revokeObjectURL(url)
  })
  selectedFiles.value = {}
  previewUrls.value = {}
  result.value = null
  persistDraft()
}

function viewLabel(view: string) {
  return viewOptions.find(item => item.key === view)?.label || view
}

function metricLabel(key: string) {
  return ({
    waist_cm: '腰围',
    hip_cm: '臀围',
    chest_cm: '胸围',
    neck_cm: '颈围',
    body_fat_scale_pct: '体脂秤',
    measured_weight_kg: '体重',
  } as Record<string, string>)[key] || key
}

function metricUnit(key: string) {
  if (key === 'body_fat_scale_pct') return '%'
  if (key === 'measured_weight_kg') return 'kg'
  return 'cm'
}
</script>

<template>
  <main class="body-photo-page" ref="pageRef">
    <header class="page-header">
      <div>
        <h1>身材阶段分析</h1>
        <p>结合多角度照片、围度与体脂秤数据给出区间估算，并与历史同角度照片比较。</p>
      </div>
      <button v-if="result" class="icon-btn" type="button" title="重新分析" @click="reset">
        <RefreshCw :size="18" />
      </button>
    </header>

    <template v-if="!result">
      <section class="measurement-panel">
        <div class="section-heading">
          <div>
            <h2>本次测量</h2>
            <p>均为选填。围度和体脂秤数据可降低单纯视觉估算的不确定性。</p>
          </div>
          <span>建议空腹、同一时段测量</span>
        </div>
        <div class="measurement-grid">
          <label v-for="field in measurementFields" :key="field.key" class="measurement-field">
            <span>{{ field.label }}</span>
            <span class="input-shell">
              <input
                v-model.number="measurements[field.key]"
                type="number"
                min="0"
                step="0.1"
                :placeholder="field.placeholder"
              />
              <small>{{ field.unit }}</small>
            </span>
          </label>
        </div>
      </section>

      <section class="upload-section">
        <div class="section-heading">
          <div>
            <h2>阶段照片</h2>
            <p>照片数量可选。保持机位、距离、光线和衣物一致，历史对比才有意义。</p>
          </div>
          <span>{{ selectedCount }}/3 已上传</span>
        </div>

        <div class="view-grid">
          <article v-for="view in viewOptions" :key="view.key" class="view-item">
            <button class="view-card" type="button" @click="chooseView(view.key)">
              <span class="view-title">{{ view.label }}</span>
              <span v-if="previewUrls[view.key]" class="view-preview">
                <img :src="previewUrls[view.key]" :alt="view.label + '照片'" />
              </span>
              <span v-else class="view-placeholder">
                <Camera :size="28" />
                <b>上传{{ view.label }}照片</b>
              </span>
              <span class="view-hint">{{ view.hint }}</span>
            </button>
            <button
              v-if="previewUrls[view.key]"
              class="remove-btn"
              type="button"
              :title="'移除' + view.label"
              @click="removeView(view.key)"
            >
              <Trash2 :size="16" />
            </button>
          </article>
        </div>

        <input ref="fileInputRef" type="file" accept="image/*" hidden @change="onFileChange" />
        <div class="shooting-checklist">
          <span><Check :size="15" /> 相机与腰部同高</span>
          <span><Check :size="15" /> 自然站立，不收腹</span>
          <span><Check :size="15" /> 均匀光线，贴身衣物</span>
        </div>
        <button class="primary-btn" :disabled="!canAnalyze" @click="doAnalyze">
          {{ loading ? '正在校验并分析...' : `开始分析（${selectedCount} 张）` }}
        </button>
      </section>
    </template>

    <section v-else class="result-section">
      <div class="result-block result-summary">
        <div>
          <span class="status-label" :class="'status-label--' + result.status">
            {{ result.status === 'completed' ? '分析完成' : result.status === 'rejected' ? '需要重拍' : '降级参考' }}
          </span>
          <h2>{{ isRejected ? '当前照片不足以可靠估算' : result.body_fat_estimate.estimated_range }}</h2>
          <p v-if="!isRejected">
            置信度 {{ Math.round(result.body_fat_estimate.confidence * 100) }}%
            <span v-if="result.auto_filled">，已同步至个人档案</span>
          </p>
        </div>
        <AlertTriangle v-if="isRejected" :size="30" />
      </div>

      <div class="result-block photo-grid">
        <button
          v-for="view in viewOptions"
          v-show="previewUrls[view.key] || result.photo_urls?.[view.key]"
          :key="view.key"
          class="photo-preview"
          type="button"
          @click="enlargedImage = previewUrls[view.key] || result.photo_urls?.[view.key] || ''"
        >
          <span>{{ view.label }}</span>
          <img :src="previewUrls[view.key] || result.photo_urls?.[view.key]" :alt="view.label + '照片'" />
          <Maximize2 :size="16" />
        </button>
      </div>

      <section v-if="isRejected" class="result-block rejection-panel">
        <h3>未通过原因</h3>
        <ul>
          <li v-for="reason in result.quality_check.rejection_reasons" :key="reason">{{ reason }}</li>
        </ul>
        <h3>重新拍摄</h3>
        <ul>
          <li v-for="guide in result.quality_check.retake_guidance" :key="guide">{{ guide }}</li>
        </ul>
      </section>

      <template v-else>
        <section class="result-block evidence-panel">
          <div class="section-heading">
            <div>
              <h3>估算依据</h3>
              <p>{{ result.body_fat_estimate.note }}</p>
            </div>
          </div>
          <div class="source-list">
            <div v-for="source in result.body_fat_estimate.sources" :key="source.key" class="source-row">
              <span>{{ source.label }}</span>
              <b>{{ source.value }}%</b>
              <small>权重 {{ Math.round(source.weight * 100) }}%</small>
            </div>
          </div>
          <div v-if="Object.keys(result.tracking_metrics || {}).length" class="metric-strip">
            <span v-if="result.tracking_metrics?.waist_to_height_ratio">
              腰高比 <b>{{ result.tracking_metrics.waist_to_height_ratio }}</b>
            </span>
            <span v-if="result.tracking_metrics?.waist_to_hip_ratio">
              腰臀比 <b>{{ result.tracking_metrics.waist_to_hip_ratio }}</b>
            </span>
          </div>
        </section>

        <section v-if="result.comparison" class="result-block comparison-panel">
          <div class="comparison-title">
            <History :size="20" />
            <h3>阶段对比</h3>
            <span v-if="result.comparison.is_comparable">
              可比视角：{{ result.comparison.comparable_views.map(viewLabel).join('、') }}
            </span>
          </div>
          <p>{{ result.comparison.summary }}</p>
          <ul v-if="result.comparison.changes?.length">
            <li v-for="change in result.comparison.changes" :key="change">{{ change }}</li>
          </ul>
          <div v-if="Object.keys(result.comparison.measurement_changes || {}).length" class="change-grid">
            <span v-for="(change, key) in result.comparison.measurement_changes" :key="key">
              {{ metricLabel(String(key)) }}
              <b :class="{ positive: change > 0, negative: change < 0 }">
                {{ change > 0 ? '+' : '' }}{{ change }}{{ metricUnit(String(key)) }}
              </b>
            </span>
          </div>
        </section>

        <div class="result-block recommendation-grid">
          <section>
            <h3>训练重点</h3>
            <div class="focus-tags">
              <span v-for="item in result.training_focus" :key="item">{{ item }}</span>
            </div>
          </section>
          <section>
            <h3>营养建议</h3>
            <p>{{ result.nutrition_suggestion }}</p>
          </section>
        </div>
      </template>

      <div class="result-actions">
        <button class="primary-btn" @click="reset">重新上传</button>
        <button class="secondary-btn" @click="router.push('/plan')">查看计划</button>
      </div>
    </section>

    <section v-if="historyItems.length" class="history-section">
      <div class="section-heading">
        <div>
          <h2>历史记录</h2>
          <p>对比结论只在同角度、相近画幅且照片质量合格时生成。</p>
        </div>
      </div>
      <div class="history-list">
        <div v-for="item in historyItems" :key="item.analysis_id" class="history-row">
          <span>{{ new Date(item.created_at).toLocaleDateString('zh-CN') }}</span>
          <b>{{ item.body_fat_estimate?.estimated_range || '未生成估算' }}</b>
          <small>{{ item.status === 'completed' ? '有效记录' : item.status === 'rejected' ? '照片被拒绝' : '降级参考' }}</small>
        </div>
      </div>
    </section>

    <div v-if="enlargedImage" class="image-dialog" role="dialog" @click="enlargedImage = ''">
      <img :src="enlargedImage" alt="身材照片大图" @click.stop />
      <button type="button" title="关闭" @click="enlargedImage = ''">×</button>
    </div>
  </main>
</template>

<style scoped>
.body-photo-page { width: min(100%, 980px); margin: 0 auto; padding-bottom: var(--space-10); }
.page-header, .section-heading, .comparison-title { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.page-header { margin-bottom: var(--space-7); }
.page-header h1 { margin: 0 0 var(--space-2); font-size: var(--text-2xl); font-weight: 800; }
.page-header p, .section-heading p { margin: 0; color: var(--color-text-secondary); line-height: var(--leading-relaxed); }
.section-heading { margin-bottom: var(--space-4); }
.section-heading h2, .section-heading h3 { margin: 0 0 4px; font-size: var(--text-lg); }
.section-heading > span { color: var(--color-text-tertiary); font-size: var(--text-xs); white-space: nowrap; }
.icon-btn { width: 40px; height: 40px; display: grid; place-items: center; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: transparent; cursor: pointer; }

.measurement-panel, .upload-section, .history-section, .evidence-panel, .comparison-panel, .rejection-panel {
  padding: var(--space-5); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); background: var(--color-surface);
}
.measurement-panel { margin-bottom: var(--space-4); }
.measurement-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.measurement-field { display: flex; flex-direction: column; gap: 6px; font-size: var(--text-sm); font-weight: 600; }
.input-shell { height: 42px; display: flex; align-items: center; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-background); }
.input-shell:focus-within { border-color: var(--color-accent); }
.input-shell input { min-width: 0; flex: 1; height: 100%; padding: 0 0 0 12px; border: 0; outline: 0; background: transparent; font: inherit; }
.input-shell small { padding: 0 12px; color: var(--color-text-tertiary); }

.view-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.view-item { position: relative; min-width: 0; }
.view-card { width: 100%; min-height: 300px; display: flex; flex-direction: column; gap: var(--space-2); padding: var(--space-3); border: 1px dashed var(--color-border); border-radius: var(--radius-sm); background: var(--color-background); cursor: pointer; }
.view-card:hover { border-color: var(--color-accent); }
.view-title { font-weight: 700; text-align: left; }
.view-preview, .view-placeholder { min-height: 190px; flex: 1; overflow: hidden; display: grid; place-items: center; border-radius: 4px; background: var(--color-border-subtle); }
.view-preview img { width: 100%; height: 100%; object-fit: contain; }
.view-placeholder { gap: 8px; align-content: center; color: var(--color-text-tertiary); }
.view-placeholder b { font-size: var(--text-sm); }
.view-hint { min-height: 38px; color: var(--color-text-tertiary); font-size: var(--text-xs); line-height: 1.5; text-align: left; }
.remove-btn { position: absolute; top: 10px; right: 10px; width: 32px; height: 32px; display: grid; place-items: center; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-surface); cursor: pointer; }
.shooting-checklist { display: flex; flex-wrap: wrap; gap: var(--space-3); margin: var(--space-4) 0; color: var(--color-text-secondary); font-size: var(--text-xs); }
.shooting-checklist span { display: inline-flex; align-items: center; gap: 5px; }

.primary-btn, .secondary-btn { height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm); font: inherit; font-weight: 700; cursor: pointer; }
.primary-btn { border: 0; background: var(--color-accent); color: white; }
.primary-btn:disabled { opacity: .5; cursor: not-allowed; }
.secondary-btn { border: 1px solid var(--color-border); background: transparent; color: var(--color-text-primary); }
.result-section { display: flex; flex-direction: column; gap: var(--space-4); }
.result-summary { display: flex; justify-content: space-between; align-items: center; padding: var(--space-5); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); background: var(--color-surface); }
.result-summary h2 { margin: 8px 0 4px; font-size: var(--text-2xl); }
.result-summary p { margin: 0; color: var(--color-text-secondary); }
.status-label { display: inline-flex; padding: 3px 8px; border-radius: 4px; font-size: var(--text-xs); font-weight: 700; }
.status-label--completed { background: oklch(0.93 0.06 145); color: oklch(0.4 0.12 145); }
.status-label--rejected { background: oklch(0.94 0.05 30); color: oklch(0.48 0.14 30); }
.status-label--fallback { background: oklch(0.94 0.05 80); color: oklch(0.48 0.12 80); }
.photo-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); }
.photo-preview { position: relative; padding: 0; overflow: hidden; border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); background: var(--color-surface); cursor: zoom-in; }
.photo-preview span { display: block; padding: 8px 10px; text-align: left; font-size: var(--text-xs); font-weight: 700; }
.photo-preview img { width: 100%; aspect-ratio: 3 / 4; display: block; object-fit: contain; background: var(--color-border-subtle); }
.photo-preview svg { position: absolute; right: 10px; bottom: 10px; padding: 6px; box-sizing: content-box; border-radius: 4px; background: rgb(255 255 255 / 88%); }
.source-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-2); }
.source-row { display: grid; gap: 3px; padding: var(--space-3); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); }
.source-row b { font-family: var(--font-mono); font-size: var(--text-lg); }
.source-row small { color: var(--color-text-tertiary); }
.metric-strip, .change-grid { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-top: var(--space-4); color: var(--color-text-secondary); font-size: var(--text-sm); }
.comparison-title { justify-content: flex-start; align-items: center; }
.comparison-title h3 { margin: 0; }
.comparison-title span { margin-left: auto; color: var(--color-text-tertiary); font-size: var(--text-xs); }
.comparison-panel p, .recommendation-grid p { color: var(--color-text-secondary); line-height: var(--leading-relaxed); }
.comparison-panel li, .rejection-panel li { margin: 6px 0; color: var(--color-text-secondary); }
.positive { color: oklch(0.48 0.14 30); }
.negative { color: oklch(0.42 0.12 145); }
.recommendation-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-4); }
.recommendation-grid section { padding: var(--space-5); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); background: var(--color-surface); }
.recommendation-grid h3, .evidence-panel h3, .comparison-panel h3, .rejection-panel h3 { margin: 0 0 var(--space-3); }
.focus-tags { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.focus-tags span { padding: 5px 10px; border-radius: 4px; background: var(--color-accent-subtle); color: var(--color-accent); font-size: var(--text-sm); font-weight: 600; }
.result-actions { display: flex; gap: var(--space-3); }
.history-section { margin-top: var(--space-6); }
.history-list { display: grid; }
.history-row { min-height: 44px; display: grid; grid-template-columns: 140px 1fr auto; align-items: center; gap: var(--space-3); border-top: 1px solid var(--color-border-subtle); font-size: var(--text-sm); }
.history-row small { color: var(--color-text-tertiary); }
.image-dialog { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 5vh 5vw; background: rgb(0 0 0 / 78%); }
.image-dialog img { max-width: 90vw; max-height: 90vh; object-fit: contain; }
.image-dialog button { position: fixed; top: 20px; right: 24px; width: 42px; height: 42px; border: 0; border-radius: 50%; background: white; font-size: 28px; cursor: pointer; }

@media (max-width: 760px) {
  .measurement-grid, .view-grid, .photo-grid, .source-list, .recommendation-grid { grid-template-columns: 1fr; }
  .view-card { min-height: 250px; }
  .page-header, .section-heading { align-items: flex-start; }
  .section-heading > span { white-space: normal; text-align: right; }
  .history-row { grid-template-columns: 1fr auto; padding: 9px 0; }
  .history-row small { grid-column: 1 / -1; }
  .result-actions { flex-direction: column; }
}
</style>
