<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getCheckinHistory, getReview } from '../api'
import type { CheckinResponse, ReviewResponse } from '../types'

const router = useRouter()
const loading = ref(false)
const reviewLoading = ref(false)
const checkins = ref<CheckinResponse[]>([])
const review = ref<ReviewResponse | null>(null)
const activeTab = ref('history')

async function fetchHistory() {
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  loading.value = true
  try {
    checkins.value = await getCheckinHistory(Number(userId), 7)
  } catch (err: any) {
    ElMessage.error('获取历史记录失败')
  } finally {
    loading.value = false
  }
}

async function fetchReview() {
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  reviewLoading.value = true
  try {
    review.value = await getReview(Number(userId))
    activeTab.value = 'review'
    ElMessage.success('复盘生成成功！')
  } catch (err: any) {
    const detail = err.response?.data?.detail || '生成复盘失败'
    ElMessage.error(detail)
  } finally {
    reviewLoading.value = false
  }
}

function formatMarkdown(text: string): string {
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/#{1,3}\s(.+)/g, '<h4>$1</h4>')
}

onMounted(() => {
  fetchHistory()
})
</script>

<template>
  <div class="history-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>打卡记录与复盘</h2>
          <div>
            <el-button
              type="primary"
              :loading="reviewLoading"
              @click="fetchReview"
              :disabled="checkins.length === 0"
            >
              生成 AI 复盘
            </el-button>
            <el-button @click="router.push('/checkin')">去打卡</el-button>
          </div>
        </div>
      </template>

      <el-tabs v-model="activeTab">
        <!-- 打卡历史 -->
        <el-tab-pane label="打卡历史" name="history">
          <div v-loading="loading" style="min-height: 200px;">
            <el-empty v-if="!loading && checkins.length === 0" description="暂无打卡记录">
              <el-button type="primary" @click="router.push('/checkin')">开始打卡</el-button>
            </el-empty>

            <el-timeline v-else>
              <el-timeline-item
                v-for="checkin in checkins"
                :key="checkin.id"
                :timestamp="checkin.date"
                placement="top"
              >
                <el-card shadow="hover">
                  <div v-if="checkin.weight" class="checkin-field">
                    <span class="field-label">体重：</span>
                    <span class="field-value">{{ checkin.weight }} kg</span>
                  </div>
                  <div v-if="checkin.foods" class="checkin-field">
                    <span class="field-label">饮食：</span>
                    <span class="field-value">{{ checkin.foods }}</span>
                  </div>
                  <div v-if="checkin.exercises" class="checkin-field">
                    <span class="field-label">运动：</span>
                    <span class="field-value">{{ checkin.exercises }}</span>
                  </div>
                  <div v-if="checkin.note" class="checkin-field">
                    <span class="field-label">备注：</span>
                    <span class="field-value">{{ checkin.note }}</span>
                  </div>
                </el-card>
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-tab-pane>

        <!-- AI 复盘 -->
        <el-tab-pane label="AI 复盘" name="review">
          <div v-if="!review" class="empty-review">
            <el-empty description="点击上方按钮生成 AI 复盘">
              <el-button
                type="primary"
                :loading="reviewLoading"
                @click="fetchReview"
                :disabled="checkins.length === 0"
              >
                生成 AI 复盘
              </el-button>
            </el-empty>
          </div>

          <template v-else>
            <el-descriptions :column="3" border style="margin-bottom: 20px;">
              <el-descriptions-item label="打卡天数">
                {{ review.checkin_count }} 天
              </el-descriptions-item>
              <el-descriptions-item label="用户 ID">
                {{ review.user_id }}
              </el-descriptions-item>
            </el-descriptions>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-card class="review-card">
                  <template #header>
                    <h3>复盘总结</h3>
                  </template>
                  <div
                    class="review-content"
                    v-html="formatMarkdown(review.review_summary)"
                  ></div>
                </el-card>
              </el-col>
              <el-col :span="12">
                <el-card class="review-card advice-card">
                  <template #header>
                    <h3>明日调整建议</h3>
                  </template>
                  <div
                    class="review-content"
                    v-html="formatMarkdown(review.next_day_advice)"
                  ></div>
                </el-card>
              </el-col>
            </el-row>
          </template>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.history-page {
  max-width: 1100px;
  margin: 0 auto;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-header h2 {
  margin: 0;
  font-size: 20px;
}

.checkin-field {
  margin-bottom: 8px;
  line-height: 1.6;
}

.field-label {
  font-weight: bold;
  color: #409eff;
  margin-right: 4px;
}

.field-value {
  color: #303133;
  white-space: pre-wrap;
}

.review-card h3 {
  margin: 0;
  font-size: 16px;
  color: #303133;
}

.review-content {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
}

.review-content :deep(h4) {
  margin: 16px 0 8px;
  color: #409eff;
}

.advice-card :deep(.el-card__header) {
  background-color: #f0f9eb;
}

.empty-review {
  padding: 40px 0;
}
</style>
