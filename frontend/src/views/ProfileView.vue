<script setup lang="ts">
import { ref, type Ref } from 'vue'
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
  body_fat_rate: undefined,
  activity_level: 'medium',
  diet_preference: 'balanced',
  goal_type: 'fat_loss',
  forbidden_foods: [],
  injuries: [],
  allergies: [],
})

const forbiddenInput = ref('')
const injuryInput = ref('')
const allergyInput = ref('')

function addToList(list: string[], inputRef: Ref<string>) {
  const item = inputRef.value.trim()
  if (item && !list.includes(item)) {
    list.push(item)
    inputRef.value = ''
  }
}

function removeFromList(list: string[], index: number) {
  list.splice(index, 1)
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
    ElMessage.success('建档成功')
    localStorage.setItem('userId', String(user.id))
    router.push('/analysis')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '建档失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="profile-page">
    <div class="page-header">
      <h1>建立你的档案</h1>
      <p>填写身体数据和饮食偏好。</p>
    </div>

    <!-- Section: Body data -->
    <section class="form-section">
      <h2 class="section-label">身体数据</h2>
      <div class="form-grid">
        <div class="form-field">
          <label class="field-label">性别</label>
          <div class="radio-group">
            <button
              class="radio-btn"
              :class="{ 'radio-btn--active': form.gender === 'male' }"
              @click="form.gender = 'male'"
            >男</button>
            <button
              class="radio-btn"
              :class="{ 'radio-btn--active': form.gender === 'female' }"
              @click="form.gender = 'female'"
            >女</button>
          </div>
        </div>
        <div class="form-field">
          <label class="field-label">年龄</label>
          <input type="number" v-model.number="form.age" min="10" max="100" class="input" />
        </div>
        <div class="form-field">
          <label class="field-label">身高 (cm)</label>
          <input type="number" v-model.number="form.height" min="100" max="250" step="0.5" class="input" />
        </div>
        <div class="form-field">
          <label class="field-label">体重 (kg)</label>
          <input type="number" v-model.number="form.weight" min="30" max="200" step="0.5" class="input" />
        </div>
        <div class="form-field">
          <label class="field-label">目标体重 (kg)</label>
          <input type="number" v-model.number="form.target_weight" min="30" max="200" step="0.5" class="input" />
        </div>
        <div class="form-field">
          <label class="field-label">体脂率 (%) <span class="field-optional">选填</span></label>
          <input
            type="number"
            v-model.number="form.body_fat_rate"
            min="3" max="60" step="0.5"
            placeholder="如 25"
            class="input"
          />
        </div>
      </div>
    </section>

    <!-- Section: Goal type -->
    <section class="form-section">
      <h2 class="section-label">训练目标</h2>
      <div class="goal-select">
        <button
          class="goal-btn"
          :class="{ 'goal-btn--active': form.goal_type === 'fat_loss' }"
          @click="form.goal_type = 'fat_loss'"
        >
          <span class="goal-icon">&#128293;</span>
          <span class="goal-name">减脂</span>
          <span class="goal-desc">热量缺口，保留肌肉，降低体脂</span>
        </button>
        <button
          class="goal-btn"
          :class="{ 'goal-btn--active': form.goal_type === 'muscle_gain' }"
          @click="form.goal_type = 'muscle_gain'"
        >
          <span class="goal-icon">&#128170;</span>
          <span class="goal-name">增肌</span>
          <span class="goal-desc">热量盈余，渐进超负荷，增加肌肉量</span>
        </button>
      </div>
    </section>

    <!-- Section: Preferences -->
    <section class="form-section">
      <h2 class="section-label">运动与饮食</h2>
      <div class="form-grid">
        <div class="form-field form-field--wide">
          <label class="field-label">活动水平</label>
          <div class="radio-group radio-group--wide">
            <button
              v-for="opt in [
                { value: 'low', label: '久坐' },
                { value: 'medium', label: '轻度活动' },
                { value: 'high', label: '高度活动' },
                { value: 'very_high', label: '极高活动' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.activity_level === opt.value }"
              @click="form.activity_level = opt.value as any"
            >{{ opt.label }}</button>
          </div>
        </div>
        <div class="form-field form-field--wide">
          <label class="field-label">饮食偏好</label>
          <div class="radio-group radio-group--wide">
            <button
              v-for="opt in [
                { value: 'balanced', label: '均衡饮食' },
                { value: 'high_protein', label: '高蛋白' },
                { value: 'low_carb', label: '低碳水' },
                { value: 'vegetarian', label: '素食' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.diet_preference === opt.value }"
              @click="form.diet_preference = opt.value as any"
            >{{ opt.label }}</button>
          </div>
        </div>
      </div>
    </section>

    <!-- Section: Restrictions -->
    <section class="form-section">
      <h2 class="section-label">忌口食物</h2>
      <div class="tag-input-row">
        <input
          v-model="forbiddenInput"
          class="input input--flex"
          placeholder="输入忌口食物，回车添加"
          @keyup.enter="addToList(form.forbidden_foods, forbiddenInput)"
        />
        <button class="btn btn-secondary" @click="addToList(form.forbidden_foods, forbiddenInput)">添加</button>
      </div>
      <div class="tags" v-if="form.forbidden_foods.length">
        <span v-for="(food, index) in form.forbidden_foods" :key="index" class="tag">
          {{ food }}
          <button class="tag-remove" @click="removeFromList(form.forbidden_foods, index)">&times;</button>
        </span>
      </div>
      <p class="field-hint" v-else>例如：牛奶、虾、花生等，没有可留空</p>
    </section>

    <!-- Section: Health -->
    <section class="form-section">
      <h2 class="section-label">健康信息 <span class="field-optional">选填，帮助生成更安全的计划</span></h2>
      <div class="form-grid">
        <div class="form-field">
          <label class="field-label">伤病部位</label>
          <div class="tag-input-row">
            <input
              v-model="injuryInput"
              class="input input--flex"
              placeholder="如：膝盖、腰部"
              @keyup.enter="addToList(form.injuries, injuryInput)"
            />
            <button class="btn btn-secondary" @click="addToList(form.injuries, injuryInput)">添加</button>
          </div>
          <div class="tags" v-if="form.injuries.length">
            <span v-for="(item, index) in form.injuries" :key="index" class="tag tag--warning">
              {{ item }}
              <button class="tag-remove" @click="removeFromList(form.injuries, index)">&times;</button>
            </span>
          </div>
          <p class="field-hint" v-else>如有膝盖、腰部等伤病，系统会避免相关动作</p>
        </div>
        <div class="form-field">
          <label class="field-label">过敏食材</label>
          <div class="tag-input-row">
            <input
              v-model="allergyInput"
              class="input input--flex"
              placeholder="如：虾、花生、牛奶"
              @keyup.enter="addToList(form.allergies, allergyInput)"
            />
            <button class="btn btn-secondary" @click="addToList(form.allergies, allergyInput)">添加</button>
          </div>
          <div class="tags" v-if="form.allergies.length">
            <span v-for="(item, index) in form.allergies" :key="index" class="tag tag--danger">
              {{ item }}
              <button class="tag-remove" @click="removeFromList(form.allergies, index)">&times;</button>
            </span>
          </div>
          <p class="field-hint" v-else>过敏食材会从饮食计划中排除</p>
        </div>
      </div>
    </section>

    <!-- Submit -->
    <div class="form-actions">
      <button class="btn btn-primary btn--lg" :disabled="loading" @click="handleSubmit">
        {{ loading ? '正在建档...' : '提交并生成计划' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.profile-page {
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

/* Form sections */
.form-section {
  margin-bottom: var(--space-8);
}

.section-label {
  font-size: var(--text-sm);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-text-tertiary);
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--color-border-subtle);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-5) var(--space-4);
}

.form-field--wide {
  grid-column: 1 / -1;
}

.field-label {
  display: block;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: var(--space-2);
}

.field-hint {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  margin-top: var(--space-2);
}

/* Inputs */
.input {
  width: 100%;
  height: 44px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-family: var(--font-family);
  color: var(--color-text-primary);
  background: var(--color-surface);
  transition: border-color var(--duration-fast) var(--ease-out);
  outline: none;
}

.input:focus {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px var(--color-accent-subtle);
}

.input--flex {
  flex: 1;
}

/* Radio buttons */
.radio-group {
  display: flex;
  gap: var(--space-2);
}

.radio-group--wide {
  flex-wrap: wrap;
}

.radio-btn {
  height: 40px;
  padding: 0 var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  font-size: var(--text-base);
  font-family: var(--font-family);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.radio-btn:hover {
  border-color: var(--color-accent);
  color: var(--color-text-primary);
}

.radio-btn--active {
  border-color: var(--color-accent);
  background: var(--color-accent-subtle);
  color: var(--color-accent);
  font-weight: 600;
}

/* Tags */
.tag-input-row {
  display: flex;
  gap: var(--space-2);
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  padding: 0 var(--space-3);
  background: var(--color-accent-subtle);
  color: var(--color-accent);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: 500;
}

.tag-remove {
  background: none;
  border: none;
  color: var(--color-accent);
  font-size: 16px;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
  opacity: 0.6;
}

.tag-remove:hover {
  opacity: 1;
}

.tag--warning {
  background: oklch(0.93 0.06 80);
  color: oklch(0.45 0.12 80);
}

.tag--danger {
  background: oklch(0.93 0.06 25);
  color: oklch(0.45 0.14 25);
}

.field-optional {
  font-weight: 400;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  text-transform: none;
  letter-spacing: normal;
}

/* Goal selector */
.goal-select {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
}

.goal-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-5) var(--space-4);
  border: 2px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  text-align: center;
}

.goal-btn:hover {
  border-color: var(--color-accent);
}

.goal-btn--active {
  border-color: var(--color-accent);
  background: var(--color-accent-subtle);
}

.goal-icon {
  font-size: 32px;
}

.goal-name {
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-family);
}

.goal-btn--active .goal-name {
  color: var(--color-accent);
}

.goal-desc {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  line-height: var(--leading-normal);
  font-family: var(--font-family);
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

.btn-secondary {
  background-color: var(--color-surface);
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
}

.btn-secondary:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.btn--lg {
  height: 48px;
  padding: 0 var(--space-8);
  font-size: var(--text-md);
}

.form-actions {
  padding-top: var(--space-4);
}

@media (max-width: 480px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
