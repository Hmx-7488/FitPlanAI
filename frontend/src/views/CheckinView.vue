<script setup lang="ts">
import { ref, onMounted, nextTick, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createCheckin } from '../api'
import { localDateStr } from '../utils/date'
import type { CheckinData } from '../types'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const pageRef = useTemplateRef<HTMLElement>('pageRef')

onMounted(() => {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.page-header'), { y: 20, opacity: 0, duration: 0.5 })
    tl.from(pageRef.value.querySelectorAll('.checkin-form'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.form-field'), { y: 15, opacity: 0, stagger: 0.06, duration: 0.3 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.form-actions'), { y: 15, opacity: 0, duration: 0.3 }, '-=0.1')
  })
})

const today = localDateStr()

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
    ElMessage.success('打卡成功')
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
  <div class="checkin-page" ref="pageRef">
    <div class="page-header">
      <h1>每日打卡</h1>
      <p>记录今天的饮食和运动。</p>
    </div>

    <div class="checkin-form">
      <!-- Date & Weight -->
      <div class="form-row">
        <div class="form-field">
          <label class="field-label">日期</label>
          <input type="date" v-model="form.date" class="input" />
        </div>
        <div class="form-field">
          <label class="field-label">体重 (kg)</label>
          <input
            type="number"
            v-model.number="form.weight"
            min="30" max="200" step="0.1"
            placeholder="选填"
            class="input"
          />
        </div>
      </div>

      <!-- Foods -->
      <div class="form-field">
        <label class="field-label">今日饮食</label>
        <textarea
          v-model="form.foods"
          rows="5"
          class="textarea"
          placeholder="记录今天吃了什么，例如：&#10;早餐：燕麦 40g + 鸡蛋 2 个 + 牛奶 200ml&#10;午餐：鸡胸肉 150g + 西兰花 200g + 糙米饭 100g&#10;晚餐：清蒸鱼 200g + 菠菜 150g"
        ></textarea>
      </div>

      <!-- Exercises -->
      <div class="form-field">
        <label class="field-label">今日运动</label>
        <textarea
          v-model="form.exercises"
          rows="4"
          class="textarea"
          placeholder="记录今天做了什么运动，例如：&#10;力量训练：深蹲 4x10 + 硬拉 3x12&#10;有氧：慢跑 30 分钟"
        ></textarea>
      </div>

      <!-- Note -->
      <div class="form-field">
        <label class="field-label">备注 <span class="field-optional">选填</span></label>
        <textarea
          v-model="form.note"
          rows="2"
          class="textarea textarea--sm"
          placeholder="今天的感受、状态、睡眠等"
        ></textarea>
      </div>

      <!-- Actions -->
      <div class="form-actions">
        <button class="btn btn-primary" :disabled="loading" @click="handleSubmit">
          {{ loading ? '提交中...' : '提交打卡' }}
        </button>
        <button class="btn btn-ghost" @click="router.push('/history')">查看历史</button>
      </div>
    </div>

    <!-- Tips -->
    <div class="tips">
      <div class="tip">
        <h3>饮食记录</h3>
        <p>尽量记录食材种类和大概份量，系统会根据记录给出调整建议。</p>
      </div>
      <div class="tip">
        <h3>运动记录</h3>
        <p>记录运动类型、时长和强度，帮助系统评估运动消耗。</p>
      </div>
      <div class="tip">
        <h3>体重追踪</h3>
        <p>建议每天早起空腹称重，日间波动 0.5kg 内属正常。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.checkin-page {
  max-width: 640px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: var(--space-8);
}

.page-header h1 {
  font-size: var(--text-2xl);
  font-weight: 800;
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
  margin-bottom: var(--space-2);
}

.page-header p {
  font-size: var(--text-md);
  color: var(--color-text-secondary);
}

.checkin-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-4);
}

.form-field {
  display: flex;
  flex-direction: column;
}

.field-label {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: var(--space-2);
}

.field-optional {
  font-weight: 400;
  color: var(--color-text-tertiary);
}

.input {
  height: 44px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-family: var(--font-family);
  color: var(--color-text-primary);
  background: var(--color-surface);
  outline: none;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.input:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-subtle);
}

.textarea {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-family: var(--font-family);
  color: var(--color-text-primary);
  background: var(--color-surface);
  resize: vertical;
  line-height: var(--leading-relaxed);
  outline: none;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.textarea:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-subtle);
}

.textarea--sm {
  min-height: 60px;
}

.form-actions {
  display: flex;
  gap: var(--space-3);
  padding-top: var(--space-2);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 44px;
  padding: 0 var(--space-6);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-weight: 600;
  font-family: var(--font-family);
  border: none;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.btn-primary {
  background-color: var(--color-accent);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background-color: var(--color-accent-hover);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-ghost {
  background: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.btn-ghost:hover {
  border-color: var(--color-text-tertiary);
  color: var(--color-text-primary);
}

.tips {
  margin-top: var(--space-10);
  padding-top: var(--space-6);
  border-top: 1px solid var(--color-border-subtle);
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-5);
}

.tip h3 {
  font-size: var(--text-sm);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: var(--space-1);
}

.tip p {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  line-height: var(--leading-normal);
}

@media (max-width: 480px) {
  .form-row {
    grid-template-columns: 1fr;
  }
  .tips {
    grid-template-columns: 1fr;
  }
}
</style>
