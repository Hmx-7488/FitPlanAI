<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { generatePlan } from '../api'
import type { PlanResponse } from '../types'

const router = useRouter()
const loading = ref(false)
const plan = ref<PlanResponse | null>(null)
const activeTab = ref('meal')

async function fetchPlan() {
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  loading.value = true
  try {
    plan.value = await generatePlan(Number(userId))
    ElMessage.success('计划生成成功！')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '生成计划失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  const userId = localStorage.getItem('userId')
  if (userId) {
    fetchPlan()
  }
})
</script>

<template>
  <div class="plan-page">
    <el-card v-if="!plan && !loading" class="empty-card">
      <el-empty description="还没有生成计划">
        <el-button type="primary" @click="fetchPlan">生成减脂计划</el-button>
      </el-empty>
    </el-card>

    <div v-loading="loading" style="min-height: 200px;">
      <template v-if="plan">
        <el-row :gutter="20" class="stat-cards">
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">每日热量目标</div>
              <div class="stat-value">{{ plan.calorie_info.target_calories }} kcal</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">蛋白质</div>
              <div class="stat-value">{{ plan.macros.protein_g }}g</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">碳水</div>
              <div class="stat-value">{{ plan.macros.carbs_g }}g</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">脂肪</div>
              <div class="stat-value">{{ plan.macros.fat_g }}g</div>
            </el-card>
          </el-col>
        </el-row>

        <el-row :gutter="20" style="margin-top: 12px;">
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">BMR</div>
              <div class="stat-value">{{ plan.calorie_info.bmr }} kcal</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">TDEE</div>
              <div class="stat-value">{{ plan.calorie_info.tdee }} kcal</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">热量缺口</div>
              <div class="stat-value">{{ plan.calorie_info.deficit }} kcal</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover">
              <div class="stat-label">饮水量</div>
              <div class="stat-value">{{ plan.macros.water_ml }} ml</div>
            </el-card>
          </el-col>
        </el-row>

        <el-card style="margin-top: 20px;">
          <el-tabs v-model="activeTab">
            <el-tab-pane label="饮食计划" name="meal">
              <div class="plan-content" v-html="formatPlan(plan.meal_plan)"></div>
            </el-tab-pane>
            <el-tab-pane label="运动计划" name="workout">
              <div class="plan-content" v-html="formatPlan(plan.workout_plan)"></div>
            </el-tab-pane>
            <el-tab-pane label="总结与建议" name="summary">
              <div class="plan-content" v-html="formatPlan(plan.summary)"></div>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </template>
    </div>
  </div>
</template>

<script lang="ts">
function formatPlan(text: string): string {
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/#{1,3}\s(.+)/g, '<h4>$1</h4>')
}
</script>

<style scoped>
.plan-page {
  max-width: 1000px;
  margin: 0 auto;
}

.empty-card {
  text-align: center;
  padding: 60px 0;
}

.stat-cards .el-card {
  text-align: center;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 22px;
  font-weight: bold;
  color: #409eff;
}

.plan-content {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
}

.plan-content :deep(h4) {
  margin: 16px 0 8px;
  color: #409eff;
}
</style>
