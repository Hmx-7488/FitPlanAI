<script setup lang="ts">
import { ref, onMounted, nextTick, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getCheckinHistory, getReview } from '../api'
import type { CheckinResponse, ReviewResponse } from '../types'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const reviewLoading = ref(false)
const pageRef = useTemplateRef<HTMLElement>('pageRef')

function animatePage() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.page-header'), { y: 20, opacity: 0, duration: 0.5 })
    tl.from(pageRef.value.querySelectorAll('.history-list'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.checkin-item'), { x: -20, opacity: 0, stagger: 0.06, duration: 0.4 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.review-section'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.review-actions'), { y: 15, opacity: 0, duration: 0.3 }, '-=0.1')
  })
}
const checkins = ref<CheckinResponse[]>([])
const review = ref<ReviewResponse | null>(null)
const activeTab = ref<'history' | 'review'>('history')

// localStorage 持久化 key
const REVIEW_STORAGE_KEY = (userId: string) => `slimagent_review_${userId}`

function saveReviewToStorage(r: ReviewResponse) {
  const userId = localStorage.getItem('userId')
  if (!userId) return
  localStorage.setItem(REVIEW_STORAGE_KEY(userId), JSON.stringify(r))
}

function loadReviewFromStorage(): ReviewResponse | null {
  const userId = localStorage.getItem('userId')
  if (!userId) return null
  const raw = localStorage.getItem(REVIEW_STORAGE_KEY(userId))
  if (!raw) return null
  try { return JSON.parse(raw) as ReviewResponse }
  catch { return null }
}

async function fetchHistory() {
  const userId = localStorage.getItem('userId')
  if (!userId) { ElMessage.warning('请先填写个人信息'); router.push('/profile'); return }
  loading.value = true
  try { checkins.value = await getCheckinHistory(Number(userId), 7) }
  catch { ElMessage.error('获取历史记录失败') }
  finally { loading.value = false }
}

async function fetchReview() {
  const userId = localStorage.getItem('userId')
  if (!userId) { ElMessage.warning('请先填写个人信息'); router.push('/profile'); return }
  reviewLoading.value = true
  try {
    const result = await getReview(Number(userId))
    review.value = result
    saveReviewToStorage(result)
    activeTab.value = 'review'
    ElMessage.success('复盘生成成功')
  }
  catch (err: any) { ElMessage.error(err.response?.data?.detail || '生成复盘失败') }
  finally { reviewLoading.value = false }
}

function formatMd(text: string): string {
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/#{1,3}\s(.+)/g, '<h4>$1</h4>')
}

onMounted(() => {
  fetchHistory()
  // 恢复上次复盘结果
  const saved = loadReviewFromStorage()
  if (saved) review.value = saved
  animatePage()
})
</script>

<template>
  <div class="history-page" ref="pageRef">
    <div class="page-header">
      <div>
        <h1>打卡记录</h1>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary" :disabled="reviewLoading || checkins.length === 0" @click="fetchReview">
          {{ reviewLoading ? '生成中...' : '生成 AI 复盘' }}
        </button>
        <button class="btn btn-ghost" @click="router.push('/checkin')">去打卡</button>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tab-bar">
      <button class="tab-btn" :class="{ 'tab-btn--active': activeTab === 'history' }" @click="activeTab = 'history'">打卡历史</button>
      <button class="tab-btn" :class="{ 'tab-btn--active': activeTab === 'review' }" @click="activeTab = 'review'">AI 复盘</button>
    </div>

    <!-- History -->
    <div v-if="activeTab === 'history'">
      <div v-if="loading" class="loading-state">
        <div class="skeleton-timeline">
          <div class="skeleton-timeline-item" v-for="i in 3" :key="i">
            <div class="skeleton skeleton-dot"></div>
            <div class="skeleton-timeline-content">
              <div class="skeleton skeleton-date"></div>
              <div class="skeleton skeleton-text"></div>
              <div class="skeleton skeleton-text skeleton-text--short"></div>
            </div>
          </div>
        </div>
      </div>

      <div v-else-if="checkins.length === 0" class="empty-state">
        <div class="empty-icon">&#128221;</div>
        <h2>暂无打卡记录</h2>
        <p>开始记录你的饮食和运动吧。</p>
        <button class="btn btn-primary" @click="router.push('/checkin')">开始打卡</button>
      </div>

      <div v-else class="timeline">
        <div v-for="c in checkins" :key="c.id" class="timeline-item">
          <div class="timeline-dot"></div>
          <div class="timeline-content">
            <div class="timeline-date">
              {{ c.date }}
              <span v-if="c.weight" class="timeline-weight">{{ c.weight }} kg</span>
            </div>
            <div v-if="c.foods" class="timeline-field">
              <span class="field-tag field-tag--food">饮食</span>
              <span class="field-text">{{ c.foods }}</span>
            </div>
            <div v-if="c.exercises" class="timeline-field">
              <span class="field-tag field-tag--exercise">运动</span>
              <span class="field-text">{{ c.exercises }}</span>
            </div>
            <div v-if="c.note" class="timeline-field">
              <span class="field-tag field-tag--note">备注</span>
              <span class="field-text">{{ c.note }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Review -->
    <div v-if="activeTab === 'review'">
      <div v-if="!review" class="empty-state">
        <div class="empty-icon">&#129302;</div>
        <h2>还没有复盘</h2>
        <p>点击上方按钮，AI 会分析你的打卡记录并给出调整建议。</p>
      </div>

      <template v-else>
        <div class="review-meta">
          <span>共 {{ review.checkin_count }} 天打卡记录</span>
        </div>

        <div class="review-grid">
          <div class="review-card">
            <h3 class="review-card-title">复盘总结</h3>
            <div class="review-content" v-html="formatMd(review.review_summary)"></div>
          </div>
          <div class="review-card review-card--advice">
            <h3 class="review-card-title">明日调整建议</h3>
            <div class="review-content" v-html="formatMd(review.next_day_advice)"></div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.history-page {
  max-width: 800px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--space-6);
}

.page-header h1 {
  font-size: var(--text-2xl);
  font-weight: 800;
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
  margin-bottom: var(--space-1);
}

.page-header p {
  font-size: var(--text-md);
  color: var(--color-text-secondary);
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* Tabs */
.tab-bar {
  display: flex;
  gap: var(--space-1);
  border-bottom: 1px solid var(--color-border-subtle);
  margin-bottom: var(--space-6);
}

.tab-btn {
  padding: var(--space-3) var(--space-4);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  font-size: var(--text-base);
  font-weight: 500;
  font-family: var(--font-family);
  color: var(--color-text-tertiary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  margin-bottom: -1px;
}

.tab-btn:hover { color: var(--color-text-primary); }

.tab-btn--active {
  color: var(--color-accent);
  border-bottom-color: var(--color-accent);
}

/* Empty & Loading */
.empty-state, .loading-state {
  text-align: center;
  padding: var(--space-12) 0;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: var(--space-4);
  opacity: 0.4;
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

/* Skeleton timeline */
.skeleton-timeline {
  text-align: left;
  max-width: 600px;
  margin: 0 auto;
  padding-left: var(--space-6);
  position: relative;
}

.skeleton-timeline::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--color-border);
}

.skeleton-timeline-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
  position: relative;
}

.skeleton-dot {
  position: absolute;
  left: calc(-1 * var(--space-6) + 3px);
  top: 8px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.skeleton-timeline-content {
  flex: 1;
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skeleton-date {
  width: 100px;
  height: 14px;
  border-radius: var(--radius-sm);
}

.skeleton-text {
  width: 100%;
  height: 14px;
  border-radius: var(--radius-sm);
}

.skeleton-text--short {
  width: 65%;
}

/* Timeline */
.timeline {
  position: relative;
  padding-left: var(--space-6);
}

.timeline::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--color-border);
}

.timeline-item {
  position: relative;
  margin-bottom: var(--space-5);
}

.timeline-dot {
  position: absolute;
  left: calc(-1 * var(--space-6) + 3px);
  top: 8px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-accent);
  border: 2px solid var(--color-surface);
}

.timeline-content {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
}

.timeline-date {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: var(--space-3);
}

.timeline-weight {
  margin-left: var(--space-3);
  padding: 2px var(--space-2);
  background: var(--color-accent-subtle);
  color: var(--color-accent);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
}

.timeline-field {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
}

.timeline-field:last-child { margin-bottom: 0; }

.field-tag {
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 2px var(--space-2);
  border-radius: 4px;
  margin-top: 2px;
}

.field-tag--food { background: oklch(0.93 0.04 145); color: oklch(0.40 0.12 145); }
.field-tag--exercise { background: oklch(0.93 0.04 250); color: oklch(0.40 0.12 250); }
.field-tag--note { background: var(--color-surface); color: var(--color-text-tertiary); border: 1px solid var(--color-border-subtle); }

.field-text { color: var(--color-text-primary); white-space: pre-wrap; }

/* Review */
.review-meta {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-5);
}

.review-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-5);
}

.review-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
  padding: var(--space-5) var(--space-6);
}

.review-card--advice {
  background: var(--color-accent-subtle);
  border-color: oklch(0.90 0.03 145);
}

.review-card-title {
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-4);
}

.review-content {
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  color: var(--color-text-primary);
}

.review-content :deep(strong) { font-weight: 700; }

.review-content :deep(h4) {
  font-size: var(--text-md);
  font-weight: 700;
  margin: var(--space-4) 0 var(--space-2);
  color: var(--color-text-primary);
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 44px;
  padding: 0 var(--space-5);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-weight: 600;
  font-family: var(--font-family);
  border: none;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover:not(:disabled) { background-color: var(--color-accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { border-color: var(--color-text-tertiary); }

@media (max-width: 640px) {
  .page-header { flex-direction: column; gap: var(--space-4); }
  .review-grid { grid-template-columns: 1fr; }
}
</style>
