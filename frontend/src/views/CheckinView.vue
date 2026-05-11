<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createCheckin } from '../api'
import type { CheckinData } from '../types'

const router = useRouter()
const loading = ref(false)

// 默认日期为今天
const today = new Date().toISOString().split('T')[0]

const form = ref<CheckinData>({
  user_id: Number(localStorage.getItem('userId')) || 0,
  date: today,
  foods: '',
  exercises: '',
  weight: undefined,
  note: '',
})

async function handleSubmit() {
  if (!form.value.user_id) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }
  if (!form.value.foods.trim() && !form.value.exercises.trim()) {
    ElMessage.warning('请至少填写饮食或运动记录')
    return
  }

  loading.value = true
  try {
    await createCheckin(form.value)
    ElMessage.success('打卡成功！')
    // 重置部分字段
    form.value.foods = ''
    form.value.exercises = ''
    form.value.note = ''
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '打卡失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="checkin-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <h2>每日打卡</h2>
          <el-tag type="success">记录今天的饮食和运动</el-tag>
        </div>
      </template>

      <el-form :model="form" label-width="100px" size="large">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="打卡日期">
              <el-date-picker
                v-model="form.date"
                type="date"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="今日体重 (kg)">
              <el-input-number
                v-model="form.weight"
                :min="30"
                :max="200"
                :step="0.1"
                :precision="1"
                placeholder="选填"
                style="width: 100%;"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="今日饮食">
          <el-input
            v-model="form.foods"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 8 }"
            placeholder="记录今天吃了什么，例如：&#10;早餐：燕麦 40g + 鸡蛋 2 个 + 牛奶 200ml&#10;午餐：鸡胸肉 150g + 西兰花 200g + 糙米饭 100g&#10;晚餐：清蒸鱼 200g + 菠菜 150g&#10;加餐：苹果 1 个"
          />
        </el-form-item>

        <el-form-item label="今日运动">
          <el-input
            v-model="form.exercises"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 6 }"
            placeholder="记录今天做了什么运动，例如：&#10;力量训练：深蹲 4x10 + 硬拉 3x12 + 卧推 4x8&#10;有氧：慢跑 30 分钟"
          />
        </el-form-item>

        <el-form-item label="备注">
          <el-input
            v-model="form.note"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            placeholder="今天的感受、状态、睡眠等（选填）"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            @click="handleSubmit"
          >
            提交打卡
          </el-button>
          <el-button size="large" @click="router.push('/history')">
            查看历史
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card style="margin-top: 20px;">
      <template #header>
        <h3>打卡小贴士</h3>
      </template>
      <el-row :gutter="16">
        <el-col :span="8">
          <div class="tip-item">
            <h4>饮食记录</h4>
            <p>尽量记录食材种类和大概份量，系统会根据记录给出调整建议。</p>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="tip-item">
            <h4>运动记录</h4>
            <p>记录运动类型、时长和强度，帮助系统评估你的运动消耗。</p>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="tip-item">
            <h4>体重追踪</h4>
            <p>建议每天早起空腹称重，体重波动 0.5kg 内属正常范围。</p>
          </div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<style scoped>
.checkin-page {
  max-width: 900px;
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

.tip-item h4 {
  font-size: 15px;
  color: #303133;
  margin-bottom: 8px;
}

.tip-item p {
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}
</style>
