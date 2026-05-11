<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createProfile } from '../api'
import type { UserProfile } from '../types'

const router = useRouter()
const loading = ref(false)

const form = ref<UserProfile>({
  gender: 'male',
  age: 25,
  height: 175,
  weight: 80,
  target_weight: 70,
  activity_level: 'medium',
  diet_preference: 'balanced',
  forbidden_foods: [],
})

const forbiddenInput = ref('')

function addForbiddenFood() {
  const food = forbiddenInput.value.trim()
  if (food && !form.value.forbidden_foods.includes(food)) {
    form.value.forbidden_foods.push(food)
    forbiddenInput.value = ''
  }
}

function removeForbiddenFood(index: number) {
  form.value.forbidden_foods.splice(index, 1)
}

async function handleSubmit() {
  if (form.value.age <= 0 || form.value.height <= 0 || form.value.weight <= 0) {
    ElMessage.warning('请填写有效的身体数据')
    return
  }
  if (form.value.target_weight <= 0) {
    ElMessage.warning('请填写有效的目标体重')
    return
  }

  loading.value = true
  try {
    const user = await createProfile(form.value)
    ElMessage.success(`建档成功！用户ID: ${user.id}`)
    localStorage.setItem('userId', String(user.id))
    router.push('/plan')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '建档失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="profile-page">
    <el-card>
      <template #header>
        <h2>个人信息录入</h2>
      </template>

      <el-form :model="form" label-width="120px" size="large">
        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="性别">
              <el-radio-group v-model="form.gender">
                <el-radio value="male">男</el-radio>
                <el-radio value="female">女</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="年龄">
              <el-input-number v-model="form.age" :min="10" :max="100" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="身高 (cm)">
              <el-input-number v-model="form.height" :min="100" :max="250" :step="0.5" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="体重 (kg)">
              <el-input-number v-model="form.weight" :min="30" :max="200" :step="0.5" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="20">
          <el-col :span="12">
            <el-form-item label="目标体重 (kg)">
              <el-input-number v-model="form.target_weight" :min="30" :max="200" :step="0.5" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="活动水平">
              <el-select v-model="form.activity_level">
                <el-option label="久坐" value="low" />
                <el-option label="轻度活动" value="medium" />
                <el-option label="高度活动" value="high" />
                <el-option label="极高活动" value="very_high" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="饮食偏好">
          <el-select v-model="form.diet_preference">
            <el-option label="均衡饮食" value="balanced" />
            <el-option label="高蛋白" value="high_protein" />
            <el-option label="低碳水" value="low_carb" />
            <el-option label="素食" value="vegetarian" />
          </el-select>
        </el-form-item>

        <el-form-item label="忌口食物">
          <div style="display: flex; gap: 8px; width: 100%;">
            <el-input v-model="forbiddenInput" placeholder="输入忌口食物" @keyup.enter="addForbiddenFood" />
            <el-button @click="addForbiddenFood">添加</el-button>
          </div>
          <div style="margin-top: 8px;">
            <el-tag
              v-for="(food, index) in form.forbidden_foods"
              :key="index"
              closable
              @close="removeForbiddenFood(index)"
              style="margin-right: 8px;"
            >
              {{ food }}
            </el-tag>
          </div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" size="large" :loading="loading" @click="handleSubmit">
            提交并生成计划
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.profile-page {
  max-width: 800px;
  margin: 0 auto;
}

h2 {
  margin: 0;
  font-size: 20px;
}
</style>
