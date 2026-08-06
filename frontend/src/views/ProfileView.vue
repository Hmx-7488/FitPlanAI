<script setup lang="ts">
import { ref, onMounted, nextTick, useTemplateRef } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createProfile, getProfile, analyzeBodyPhoto } from '../api'
import type { UserProfile } from '../types'
import gsap from 'gsap'

const router = useRouter()
const loading = ref(false)
const profileLoaded = ref(false)
const pageRef = useTemplateRef<HTMLElement>('pageRef')

function animatePage() {
  nextTick(() => {
    if (!pageRef.value) return
    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } })
    tl.from(pageRef.value.querySelectorAll('.page-header'), { y: 20, opacity: 0, duration: 0.5 })
    tl.from(pageRef.value.querySelectorAll('.form-grid'), { y: 25, opacity: 0, duration: 0.5 }, '-=0.3')
    tl.from(pageRef.value.querySelectorAll('.form-field'), { y: 15, opacity: 0, stagger: 0.05, duration: 0.3 }, '-=0.2')
    tl.from(pageRef.value.querySelectorAll('.form-actions, .submit-section'), { y: 15, opacity: 0, duration: 0.4 }, '-=0.1')
  })
}

// 建档流程状态：form → photo → analyzing → result
const step = ref<'form' | 'photo' | 'analyzing' | 'result'>('form')
const createdUserId = ref<number | null>(null)
const showAdvanced = ref(false)
const bodyPhotoFile = ref<File | null>(null)
const bodyPhotoPreview = ref('')
const bodyFatResult = ref<{
  photo_url: string
  body_fat_estimate: number | null
  body_fat_range: string
  training_focus: string[]
  nutrition_suggestion: string
  note: string
  auto_filled: boolean
} | null>(null)

const form = ref<UserProfile>({
  gender: 'male',
  age: 25,
  height: 175,
  weight: 80,
  target_weight: 70,
  target_weeks: 8,
  body_fat_rate: undefined,
  activity_level: 'medium',
  diet_preference: 'balanced',
  goal_type: 'fat_loss',
  forbidden_foods: [],
  injuries: [],
  allergies: [],
  // 训练条件
  training_days_per_week: 3,
  session_duration_minutes: 60,
  training_location: 'gym',
  equipment: [],
  training_experience: 'beginner',
  preferred_training_time: 'evening',
  // 中国饮食习惯
  region_preference: 'balanced',
  meal_scenario: 'home_cooking',
  prep_time_limit_minutes: 30,
})

const equipmentInput = ref('')

const forbiddenInput = ref('')
const injuryInput = ref('')
const allergyInput = ref('')

function addToList(list: string[], inputValue: string) {
  const item = inputValue.trim()
  if (item && !list.includes(item)) {
    list.push(item)
  }
}

function addForbiddenFood() {
  addToList(form.value.forbidden_foods, forbiddenInput.value)
  forbiddenInput.value = ''
}

function addInjury() {
  addToList(form.value.injuries, injuryInput.value)
  injuryInput.value = ''
}

function addAllergy() {
  addToList(form.value.allergies, allergyInput.value)
  allergyInput.value = ''
}

function addEquipment() {
  addToList(form.value.equipment, equipmentInput.value)
  equipmentInput.value = ''
}

function removeFromList(list: string[], index: number) {
  list.splice(index, 1)
}

// 页面加载时恢复已有档案数据
onMounted(async () => {
  const userId = localStorage.getItem('userId')
  if (!userId) return
  try {
    const existing = await getProfile(Number(userId))
    if (existing) {
      form.value.gender = existing.gender
      form.value.age = existing.age
      form.value.height = existing.height
      form.value.weight = existing.weight
      form.value.target_weight = existing.target_weight
      form.value.target_weeks = existing.target_weeks ?? null
      form.value.body_fat_rate = existing.body_fat_rate ?? undefined
      form.value.activity_level = existing.activity_level
      form.value.diet_preference = existing.diet_preference
      form.value.goal_type = existing.goal_type
      form.value.forbidden_foods = [...existing.forbidden_foods]
      form.value.injuries = [...existing.injuries]
      form.value.allergies = [...existing.allergies]
      // 训练条件
      form.value.training_days_per_week = existing.training_days_per_week
      form.value.session_duration_minutes = existing.session_duration_minutes
      form.value.training_location = existing.training_location
      form.value.equipment = [...(existing.equipment || [])]
      form.value.training_experience = existing.training_experience
      form.value.preferred_training_time = existing.preferred_training_time
      // 中国饮食习惯
      form.value.region_preference = existing.region_preference
      form.value.meal_scenario = existing.meal_scenario
      form.value.prep_time_limit_minutes = existing.prep_time_limit_minutes
      profileLoaded.value = true
    }
  } catch { /* 首次建档，无已有数据 */ }
  animatePage()
})

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
    localStorage.setItem('userId', String(user.id))
    createdUserId.value = user.id

    if (profileLoaded.value) {
      // 修改模式，直接跳转
      ElMessage.success('档案已更新')
      router.push('/analysis')
    } else {
      // 新建档，进入身材照片步骤
      ElMessage.success('建档成功')
      step.value = 'photo'
    }
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '建档失败')
  } finally {
    loading.value = false
  }
}

function onBodyPhotoChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  bodyPhotoFile.value = file
  bodyPhotoPreview.value = URL.createObjectURL(file)
}

async function doBodyPhotoAnalyze() {
  if (!bodyPhotoFile.value || !createdUserId.value) return
  step.value = 'analyzing'
  try {
    // 统一走身材分析主接口（质量校验 + 置信度门槛 + 历史记录）
    const result = await analyzeBodyPhoto(createdUserId.value, { front: bodyPhotoFile.value })
    const estimate = result.body_fat_estimate?.value ?? null
    bodyFatResult.value = {
      photo_url: result.photo_url || '',
      body_fat_estimate: estimate,
      body_fat_range: result.body_fat_estimate?.estimated_range || '',
      training_focus: result.training_focus || [],
      nutrition_suggestion: result.nutrition_suggestion || '',
      note: result.body_fat_estimate?.note || '',
      auto_filled: result.auto_filled === true,
    }
    if (estimate !== null && result.auto_filled) {
      // 只有达到置信度门槛被后端写入档案时才更新表单
      form.value.body_fat_rate = estimate
      ElMessage.success('身材分析完成，体脂率已自动填入')
    } else if (estimate !== null) {
      ElMessage.success('分析完成，置信度不足未写入档案，可手动填写体脂率')
    } else {
      ElMessage.warning('照片质量未通过，未生成体脂估算，可重新拍摄或跳过')
    }
    step.value = 'result'
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '分析失败')
    step.value = 'photo'
  }
}

function skipPhoto() {
  router.push('/analysis')
}

function goToAnalysis() {
  router.push('/analysis')
}
</script>

<template>
  <div class="profile-page" ref="pageRef">
    <div class="page-header">
      <h1>{{ profileLoaded ? '修改你的档案' : '建立你的档案' }}</h1>
      <p>{{ profileLoaded ? '修改身体数据和偏好，提交后可重新生成计划。' : '填写身体数据和饮食偏好。' }}</p>
    </div>

    <!-- ====== Step 1: 表单 ====== -->
    <div v-if="step === 'form'">

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
          <label class="field-label">目标周期 <span class="field-optional">选填，用于阶段调整</span></label>
          <div class="radio-group">
            <button
              v-for="w in [4, 8, 12, 16]"
              :key="w"
              class="radio-btn radio-btn--num"
              :class="{ 'radio-btn--active': form.target_weeks === w }"
              @click="form.target_weeks = form.target_weeks === w ? null : w"
              type="button"
            >{{ w }}周</button>
          </div>
        </div>
        <!-- 体脂率：折叠在高级选项中，大部分用户不需要手动填 -->
        <div class="form-field form-field--wide">
          <button class="advanced-toggle" @click="showAdvanced = !showAdvanced" type="button">
            <span>{{ showAdvanced ? '▾' : '▸' }} 高级选项</span>
            <span class="advanced-hint" v-if="!form.body_fat_rate">可手动填写体脂率，或后续通过身材照片 AI 估算</span>
            <span class="advanced-filled" v-else>体脂率 {{ form.body_fat_rate }}%</span>
          </button>
          <div v-if="showAdvanced" class="advanced-content">
            <label class="field-label">体脂率 (%) <span class="field-optional">选填</span></label>
            <input
              type="number"
              v-model.number="form.body_fat_rate"
              min="3" max="60" step="0.5"
              placeholder="如 25，不知道可留空"
              class="input"
              style="max-width: 200px"
            />
            <p class="field-hint">不知道体脂率没关系，建档后可以上传身材照片让 AI 估算。</p>
          </div>
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

    <!-- Section: Training conditions -->
    <section class="form-section">
      <h2 class="section-label">训练条件 <span class="field-optional">选填，帮助生成更贴合实际的计划</span></h2>
      <div class="form-grid">
        <div class="form-field">
          <label class="field-label">每周训练天数</label>
          <div class="radio-group">
            <button
              v-for="d in [2, 3, 4, 5, 6]"
              :key="d"
              class="radio-btn radio-btn--num"
              :class="{ 'radio-btn--active': form.training_days_per_week === d }"
              @click="form.training_days_per_week = d"
            >{{ d }}天</button>
          </div>
        </div>
        <div class="form-field">
          <label class="field-label">每次训练时长</label>
          <div class="radio-group">
            <button
              v-for="opt in [
                { value: 30, label: '30分钟' },
                { value: 45, label: '45分钟' },
                { value: 60, label: '60分钟' },
                { value: 90, label: '90分钟' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.session_duration_minutes === opt.value }"
              @click="form.session_duration_minutes = opt.value"
            >{{ opt.label }}</button>
          </div>
        </div>
        <div class="form-field">
          <label class="field-label">训练地点</label>
          <div class="radio-group">
            <button
              v-for="opt in [
                { value: 'gym', label: '健身房' },
                { value: 'home', label: '家里' },
                { value: 'outdoor', label: '户外' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.training_location === opt.value }"
              @click="form.training_location = opt.value as any"
            >{{ opt.label }}</button>
          </div>
        </div>
        <div class="form-field">
          <label class="field-label">训练经验</label>
          <div class="radio-group">
            <button
              v-for="opt in [
                { value: 'beginner', label: '新手' },
                { value: 'intermediate', label: '有基础' },
                { value: 'advanced', label: '进阶' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.training_experience === opt.value }"
              @click="form.training_experience = opt.value as any"
            >{{ opt.label }}</button>
          </div>
        </div>
        <div class="form-field">
          <label class="field-label">偏好训练时间</label>
          <div class="radio-group">
            <button
              v-for="opt in [
                { value: 'morning', label: '早上' },
                { value: 'afternoon', label: '下午' },
                { value: 'evening', label: '晚上' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.preferred_training_time === opt.value }"
              @click="form.preferred_training_time = opt.value as any"
            >{{ opt.label }}</button>
          </div>
        </div>
      </div>
      <!-- Equipment tags -->
      <div class="form-field" style="margin-top: var(--space-4)">
        <label class="field-label">可用器械 <span class="field-optional">选填</span></label>
        <div class="tag-input-row">
          <input
            v-model="equipmentInput"
            class="input input--flex"
            placeholder="如：哑铃、杠铃、跑步机、弹力带"
            @keyup.enter="addEquipment"
          />
          <button class="btn btn-secondary" @click="addEquipment">添加</button>
        </div>
        <div class="tags" v-if="form.equipment.length">
          <span v-for="(item, index) in form.equipment" :key="index" class="tag">
            {{ item }}
            <button class="tag-remove" @click="removeFromList(form.equipment, index)">&times;</button>
          </span>
        </div>
        <p class="field-hint" v-else>家里训练可填：哑铃、弹力带、瑜伽垫等</p>
      </div>
    </section>

    <!-- Section: Chinese diet -->
    <section class="form-section">
      <h2 class="section-label">饮食习惯 <span class="field-optional">选填，让计划更贴近你的生活</span></h2>
      <div class="form-grid">
        <div class="form-field form-field--wide">
          <label class="field-label">地域口味</label>
          <div class="radio-group radio-group--wide">
            <button
              v-for="opt in [
                { value: 'balanced', label: '不限' },
                { value: 'south_china', label: '南方' },
                { value: 'north_china', label: '北方' },
                { value: 'sichuan', label: '川湘' },
                { value: 'cantonese', label: '粤式' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.region_preference === opt.value }"
              @click="form.region_preference = opt.value as any"
            >{{ opt.label }}</button>
          </div>
        </div>
        <div class="form-field form-field--wide">
          <label class="field-label">主要饮食场景</label>
          <div class="radio-group radio-group--wide">
            <button
              v-for="opt in [
                { value: 'home_cooking', label: '自己做饭' },
                { value: 'takeout', label: '点外卖' },
                { value: 'canteen', label: '食堂' },
                { value: 'convenience_store', label: '便利店' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.meal_scenario === opt.value }"
              @click="form.meal_scenario = opt.value as any"
            >{{ opt.label }}</button>
          </div>
        </div>
        <div class="form-field">
          <label class="field-label">备餐时间限制</label>
          <div class="radio-group">
            <button
              v-for="opt in [
                { value: 5, label: '5分钟' },
                { value: 15, label: '15分钟' },
                { value: 30, label: '30分钟' },
                { value: 60, label: '不限' },
              ]"
              :key="opt.value"
              class="radio-btn"
              :class="{ 'radio-btn--active': form.prep_time_limit_minutes === opt.value }"
              @click="form.prep_time_limit_minutes = opt.value"
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
          @keyup.enter="addForbiddenFood"
        />
        <button class="btn btn-secondary" @click="addForbiddenFood">添加</button>
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
              @keyup.enter="addInjury"
            />
            <button class="btn btn-secondary" @click="addInjury">添加</button>
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
              @keyup.enter="addAllergy"
            />
            <button class="btn btn-secondary" @click="addAllergy">添加</button>
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
        {{ loading ? '正在保存...' : (profileLoaded ? '保存修改' : '提交并生成计划') }}
      </button>
    </div>

    </div><!-- /step === 'form' -->

    <!-- ====== Step 2: 身材照片上传 ====== -->
    <div v-if="step === 'photo'">
      <div class="photo-step">
        <div class="photo-step-header">
          <span class="step-icon">&#128247;</span>
          <h2>上传身材照片（可选）</h2>
          <p>AI 会分析照片估算体脂率，让计划更精准。不上传也可以。</p>
          <p class="privacy-hint">照片仅保存在本应用本地存储，可在身材分析页历史记录中随时删除。</p>
        </div>

        <div class="upload-area" @click="($refs.bodyFileInput as HTMLInputElement).click()">
          <div v-if="bodyPhotoPreview" class="preview">
            <img :src="bodyPhotoPreview" alt="身材照片预览" />
          </div>
          <div v-else class="upload-placeholder">
            <span class="upload-icon">&#128100;</span>
            <p>点击选择全身照片</p>
            <span class="upload-hint">建议正面站立，光线充足，全身入镜</span>
          </div>
        </div>
        <input ref="bodyFileInput" type="file" accept="image/*" style="display:none" @change="onBodyPhotoChange" />

        <div class="photo-actions">
          <button class="btn btn-primary" :disabled="!bodyPhotoFile" @click="doBodyPhotoAnalyze">
            AI 分析身材
          </button>
          <button class="btn btn-ghost" @click="skipPhoto">跳过，直接查看分析</button>
        </div>
      </div>
    </div>

    <!-- ====== Step 3: 分析中 ====== -->
    <div v-if="step === 'analyzing'">
      <div class="analyzing-step">
        <div class="loading-icon">&#128270;</div>
        <p class="loading-msg">AI 正在分析身材照片...</p>
        <div class="loading-bar"><div class="loading-fill"></div></div>
        <p class="loading-hint">正在估算体脂率和训练重点，约需 10-20 秒</p>
      </div>
    </div>

    <!-- ====== Step 4: 分析结果 ====== -->
    <div v-if="step === 'result' && bodyFatResult">
      <div class="result-step">
        <div class="result-header">
          <h2>身材分析结果</h2>
        </div>

        <div class="result-photo" v-if="bodyFatResult.photo_url">
          <img :src="bodyFatResult.photo_url" alt="身材照片" />
        </div>

        <div class="result-card result-card--highlight">
          <template v-if="bodyFatResult.body_fat_estimate !== null">
            <div class="result-main">
              <span class="result-value">{{ bodyFatResult.body_fat_estimate }}</span>
              <span class="result-unit">%</span>
            </div>
            <div class="result-label">AI 估算体脂率</div>
            <div class="result-range" v-if="bodyFatResult.body_fat_range">范围：{{ bodyFatResult.body_fat_range }}</div>
          </template>
          <div v-else class="result-label">本次未生成体脂估算</div>
          <p class="result-note">{{ bodyFatResult.note }}</p>
          <div class="auto-filled-badge" v-if="bodyFatResult.auto_filled">&#10003; 已自动填入档案</div>
        </div>

        <div class="result-card" v-if="bodyFatResult.training_focus.length">
          <h3>训练重点建议</h3>
          <div class="focus-tags">
            <span v-for="f in bodyFatResult.training_focus" :key="f" class="focus-tag">{{ f }}</span>
          </div>
        </div>

        <div class="result-card result-card--accent" v-if="bodyFatResult.nutrition_suggestion">
          <h3>营养建议</h3>
          <p>{{ bodyFatResult.nutrition_suggestion }}</p>
        </div>

        <div class="result-actions">
          <button class="btn btn-primary" @click="goToAnalysis">查看身体画像分析</button>
          <button class="btn btn-ghost" @click="step = 'photo'">重新拍照</button>
        </div>
      </div>
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

.radio-btn--num {
  min-width: 52px;
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

/* Advanced toggle */
.advanced-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: none;
  border: none;
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
  font-family: var(--font-family);
  padding: var(--space-2) 0;
  transition: color var(--duration-fast) var(--ease-out);
}
.advanced-toggle:hover { color: var(--color-accent); }
.advanced-hint { font-weight: 400; color: var(--color-text-tertiary); }
.advanced-filled { font-weight: 400; color: var(--color-accent); }
.advanced-content {
  margin-top: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md);
}

/* Photo step */
.photo-step { text-align: center; padding: var(--space-6) 0; }
.photo-step-header { margin-bottom: var(--space-6); }
.step-icon { font-size: 48px; display: block; margin-bottom: var(--space-3); opacity: 0.5; }
.photo-step-header h2 { font-size: var(--text-xl); font-weight: 700; margin-bottom: var(--space-2); }
.photo-step-header p { color: var(--color-text-secondary); }
.photo-step-header .privacy-hint { margin-top: var(--space-1); font-size: var(--text-sm); color: var(--color-text-tertiary); }

.upload-area {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-8);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
  margin-bottom: var(--space-5);
  max-width: 400px;
  margin-left: auto;
  margin-right: auto;
}
.upload-area:hover { border-color: var(--color-accent); }
.upload-placeholder { color: var(--color-text-tertiary); }
.upload-icon { font-size: 48px; display: block; margin-bottom: var(--space-2); opacity: 0.4; }
.upload-hint { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.preview img { max-width: 100%; max-height: 250px; border-radius: var(--radius-sm); }

.photo-actions { display: flex; justify-content: center; gap: var(--space-3); }

/* Analyzing step */
.analyzing-step { text-align: center; padding: var(--space-12) 0; }
.loading-icon { font-size: 48px; margin-bottom: var(--space-4); opacity: 0.5; }
.loading-msg { font-size: var(--text-md); font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-4); }
.loading-bar { height: 4px; background: var(--color-border-subtle); border-radius: 2px; overflow: hidden; max-width: 300px; margin: 0 auto var(--space-3); }
.loading-fill { height: 100%; background: var(--color-accent); border-radius: 2px; animation: loadPulse 2s ease-in-out infinite; width: 60%; }
@keyframes loadPulse { 0%,100% { width: 30%; } 50% { width: 80%; } }
.loading-hint { font-size: var(--text-sm); color: var(--color-text-tertiary); }

/* Result step */
.result-step { display: flex; flex-direction: column; gap: var(--space-4); }
.result-header h2 { font-size: var(--text-xl); font-weight: 700; }
.result-photo img { max-width: 100%; max-height: 200px; border-radius: var(--radius-sm); }

.result-card { background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-md); padding: var(--space-5); }
.result-card h3 { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-3); }
.result-card--highlight { text-align: center; background: var(--color-accent-subtle); border-color: oklch(0.90 0.03 145); }
.result-card--accent { background: var(--color-accent-subtle); border-color: oklch(0.90 0.03 145); }

.result-main { display: flex; align-items: baseline; justify-content: center; gap: var(--space-1); margin-bottom: var(--space-1); }
.result-value { font-family: var(--font-mono); font-size: 48px; font-weight: 800; color: var(--color-accent); line-height: 1; }
.result-unit { font-size: var(--text-xl); color: var(--color-accent); }
.result-label { font-size: var(--text-sm); font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-1); }
.result-range { font-size: var(--text-sm); color: var(--color-text-secondary); font-family: var(--font-mono); margin-bottom: var(--space-2); }
.result-note { font-size: var(--text-sm); color: var(--color-text-tertiary); margin-bottom: var(--space-3); }
.auto-filled-badge { display: inline-block; font-size: var(--text-xs); font-weight: 600; padding: 2px 10px; background: oklch(0.93 0.04 145); color: oklch(0.40 0.12 145); border-radius: var(--radius-sm); }

.focus-tags { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.focus-tag { font-size: var(--text-sm); font-weight: 600; padding: 4px 12px; background: var(--color-accent-subtle); color: var(--color-accent); border-radius: var(--radius-sm); }

.result-actions { display: flex; gap: var(--space-3); }
</style>
