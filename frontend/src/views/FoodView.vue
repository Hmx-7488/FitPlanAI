<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { recognizeIngredients, confirmIngredients, generateRecipes, getLatestRecipe } from '../api'
import type { IngredientItem, RecognizeResponse, RecipeResponse } from '../types'

const router = useRouter()

// 状态：upload | recognizing | confirm | generating | result
const step = ref<'upload' | 'recognizing' | 'confirm' | 'generating' | 'result'>('upload')
const selectedFile = ref<File | null>(null)
const previewUrl = ref('')
const recognition = ref<RecognizeResponse | null>(null)
const editableIngredients = ref<IngredientItem[]>([])
const recipes = ref<RecipeResponse | null>(null)
const loadingMsg = ref('')

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  selectedFile.value = file
  previewUrl.value = URL.createObjectURL(file)
}

async function doRecognize() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择图片')
    return
  }
  const userId = localStorage.getItem('userId')
  if (!userId) {
    ElMessage.warning('请先填写个人信息')
    router.push('/profile')
    return
  }

  step.value = 'recognizing'
  loadingMsg.value = 'AI 正在识别食材...'

  try {
    const result = await recognizeIngredients(Number(userId), selectedFile.value)
    recognition.value = result
    editableIngredients.value = result.ingredients.map(i => ({ ...i }))
    step.value = 'confirm'
    ElMessage.success('识别完成，请确认食材')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '识别失败')
    step.value = 'upload'
  }
}

function updateWeight(index: number, value: string) {
  const num = parseFloat(value)
  if (!isNaN(num) && num > 0) {
    editableIngredients.value[index].estimated_weight_g = num
  }
}

function removeIngredient(index: number) {
  editableIngredients.value.splice(index, 1)
}

function addManualIngredient() {
  editableIngredients.value.push({
    name: 'custom',
    display_name: '',
    estimated_weight_g: 100,
    confidence: 1.0,
    need_confirm: true,
  })
}

async function doConfirmAndGenerate() {
  if (!recognition.value) return
  const userId = localStorage.getItem('userId')
  if (!userId) return

  // 过滤掉空名称的
  const valid = editableIngredients.value.filter(i => i.display_name.trim())
  if (valid.length === 0) {
    ElMessage.warning('请至少保留一个食材')
    return
  }

  step.value = 'generating'
  loadingMsg.value = '正在确认食材...'

  try {
    await confirmIngredients(recognition.value.recognition_id, valid)
    loadingMsg.value = 'AI 正在生成轻食菜谱...'
    const result = await generateRecipes(
      Number(userId), recognition.value.recognition_id, valid
    )
    recipes.value = result
    step.value = 'result'
    ElMessage.success('菜谱生成成功')
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '生成失败')
    step.value = 'confirm'
  }
}

function resetAll() {
  step.value = 'upload'
  selectedFile.value = null
  previewUrl.value = ''
  recognition.value = null
  editableIngredients.value = []
  recipes.value = null
}

function formatRecipe(text: string): string {
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/#{1,3}\s(.+)/g, '<h4>$1</h4>')
}

// 页面加载时恢复已有菜谱
onMounted(async () => {
  const userId = localStorage.getItem('userId')
  if (!userId) return
  try {
    const existing = await getLatestRecipe(Number(userId))
    if (existing && existing.recipe_content) {
      recipes.value = existing as RecipeResponse
      step.value = 'result'
    }
  } catch { /* ignore */ }
})
</script>

<template>
  <div class="food-page">
    <!-- Header -->
    <div class="page-header">
      <h1>食材识别</h1>
      <p>拍照识别食材，AI 生成轻食菜谱。</p>
    </div>

    <!-- Step 1: Upload -->
    <div v-if="step === 'upload'" class="upload-section">
      <div class="upload-area" @click="($refs.fileInput as HTMLInputElement).click()">
        <div v-if="previewUrl" class="preview">
          <img :src="previewUrl" alt="预览" />
        </div>
        <div v-else class="upload-placeholder">
          <span class="upload-icon">&#128247;</span>
          <p>点击选择食材照片</p>
          <span class="upload-hint">支持 JPG、PNG，最大 10MB</span>
        </div>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept="image/*"
        style="display: none"
        @change="onFileChange"
      />
      <div class="upload-actions">
        <button class="btn btn-primary" :disabled="!selectedFile" @click="doRecognize">
          开始识别
        </button>
      </div>
    </div>

    <!-- Step 2: Recognizing -->
    <div v-if="step === 'recognizing'" class="loading-section">
      <div class="loading-icon">&#128270;</div>
      <p class="loading-msg">{{ loadingMsg }}</p>
      <div class="loading-bar"><div class="loading-fill"></div></div>
      <p class="loading-hint">Vision Model 正在分析图片，约需 10-30 秒</p>
    </div>

    <!-- Step 3: Confirm -->
    <div v-if="step === 'confirm'" class="confirm-section">
      <div class="confirm-header">
        <h2>识别结果</h2>
        <p>请确认食材和重量，可修改或删除。</p>
      </div>

      <!-- 预览图 -->
      <div class="confirm-preview" v-if="previewUrl">
        <img :src="previewUrl" alt="食材照片" />
      </div>

      <!-- 食材列表 -->
      <div class="ingredient-list">
        <div
          v-for="(item, index) in editableIngredients"
          :key="index"
          class="ingredient-card"
        >
          <div class="ingredient-info">
            <input
              v-model="item.display_name"
              class="ingredient-name-input"
              placeholder="食材名称"
            />
            <span class="confidence" v-if="item.confidence < 1">
              置信度 {{ (item.confidence * 100).toFixed(0) }}%
            </span>
          </div>
          <div class="ingredient-weight">
            <input
              type="number"
              :value="item.estimated_weight_g"
              @input="updateWeight(index, ($event.target as HTMLInputElement).value)"
              min="1" max="5000" step="10"
              class="weight-input"
            />
            <span class="weight-unit">g</span>
          </div>
          <button class="remove-btn" @click="removeIngredient(index)">&times;</button>
        </div>
      </div>

      <div class="confirm-actions">
        <button class="btn btn-secondary" @click="addManualIngredient">+ 手动添加</button>
        <button class="btn btn-primary" @click="doConfirmAndGenerate">确认并生成菜谱</button>
        <button class="btn btn-ghost" @click="resetAll">重新拍照</button>
      </div>
    </div>

    <!-- Step 4: Generating -->
    <div v-if="step === 'generating'" class="loading-section">
      <div class="loading-icon">&#127859;</div>
      <p class="loading-msg">{{ loadingMsg }}</p>
      <div class="loading-bar"><div class="loading-fill"></div></div>
    </div>

    <!-- Step 5: Result -->
    <div v-if="step === 'result' && recipes" class="result-section">
      <div class="result-header">
        <h2>轻食方案</h2>
        <div class="result-meta">
          <span class="meta-item">共 {{ recipes.recipes.length }} 个方案</span>
          <span class="meta-item">总热量约 {{ recipes.total_calories }} kcal</span>
          <span class="meta-item">蛋白质约 {{ recipes.total_protein.toFixed(0) }}g</span>
        </div>
      </div>

      <!-- 菜谱卡片 -->
      <div class="recipe-cards">
        <div v-for="(r, index) in recipes.recipes" :key="index" class="recipe-card">
          <!-- 菜谱图片 -->
          <div class="recipe-image-wrap" v-if="r.image">
            <img
              :src="r.image.url"
              :alt="r.image.alt"
              class="recipe-image"
              @error="($event.target as HTMLImageElement).src = '/default-recipe.svg'"
            />
          </div>
          <h3 class="recipe-name">{{ r.name }}</h3>
          <div class="recipe-tags">
            <span class="recipe-tag recipe-tag--cal">{{ r.calories_est }} kcal</span>
            <span class="recipe-tag recipe-tag--pro">{{ r.protein_est.toFixed(0) }}g 蛋白</span>
            <span class="recipe-tag recipe-tag--carb">{{ r.carbs_est.toFixed(0) }}g 碳水</span>
            <span class="recipe-tag recipe-tag--fat">{{ r.fat_est.toFixed(0) }}g 脂肪</span>
          </div>
          <div class="recipe-ingredients">
            <span v-for="ing in r.ingredients" :key="ing" class="recipe-ing">{{ ing }}</span>
          </div>
          <p class="recipe-steps">{{ r.steps }}</p>
          <!-- 替代食材 -->
          <div v-if="r.substitute_ingredients?.length" class="recipe-substitutes">
            <h4 class="sub-title">替代建议</h4>
            <div v-for="sub in r.substitute_ingredients" :key="sub.missing" class="sub-item">
              <span class="sub-missing">{{ sub.missing }}</span>
              <span class="sub-arrow">→</span>
              <span v-for="alt in sub.alternatives" :key="alt" class="sub-alt">{{ alt }}</span>
            </div>
          </div>
          <!-- 购物清单 -->
          <div v-if="r.shopping_list?.length" class="recipe-shopping">
            <span class="shopping-label">需要购买：</span>
            <span v-for="item in r.shopping_list" :key="item" class="shopping-item">{{ item }}</span>
          </div>
        </div>
      </div>

      <!-- 完整菜谱 -->
      <details class="full-recipe">
        <summary>查看完整菜谱文本</summary>
        <div class="full-recipe-content" v-html="formatRecipe(recipes.recipe_content)"></div>
      </details>

      <div class="result-actions">
        <button class="btn btn-primary" @click="resetAll">再拍一张</button>
        <button class="btn btn-ghost" @click="router.push('/plan')">查看减脂计划</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.food-page { max-width: 700px; margin: 0 auto; }

.page-header { margin-bottom: var(--space-8); }
.page-header h1 { font-size: var(--text-2xl); font-weight: 800; color: var(--color-text-primary); letter-spacing: -0.02em; margin-bottom: var(--space-2); }
.page-header p { font-size: var(--text-md); color: var(--color-text-secondary); }

/* Upload */
.upload-section { text-align: center; }
.upload-area {
  border: 2px dashed var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-10);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
  margin-bottom: var(--space-5);
}
.upload-area:hover { border-color: var(--color-accent); }
.upload-placeholder { color: var(--color-text-tertiary); }
.upload-icon { font-size: 48px; display: block; margin-bottom: var(--space-3); opacity: 0.4; }
.upload-hint { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.preview img { max-width: 100%; max-height: 300px; border-radius: var(--radius-sm); }
.upload-actions { display: flex; justify-content: center; gap: var(--space-3); }

/* Loading */
.loading-section { text-align: center; padding: var(--space-12) 0; }
.loading-icon { font-size: 48px; margin-bottom: var(--space-4); opacity: 0.5; }
.loading-msg { font-size: var(--text-md); font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-4); }
.loading-bar { height: 4px; background: var(--color-border-subtle); border-radius: 2px; overflow: hidden; max-width: 300px; margin: 0 auto var(--space-3); }
.loading-fill { height: 100%; background: var(--color-accent); border-radius: 2px; animation: loadPulse 2s ease-in-out infinite; width: 60%; }
@keyframes loadPulse { 0%,100% { width: 30%; } 50% { width: 80%; } }
.loading-hint { font-size: var(--text-sm); color: var(--color-text-tertiary); }

/* Confirm */
.confirm-header { margin-bottom: var(--space-5); }
.confirm-header h2 { font-size: var(--text-xl); font-weight: 700; margin-bottom: var(--space-1); }
.confirm-header p { color: var(--color-text-secondary); }
.confirm-preview { margin-bottom: var(--space-5); }
.confirm-preview img { max-width: 100%; max-height: 200px; border-radius: var(--radius-sm); }

.ingredient-list { display: flex; flex-direction: column; gap: var(--space-3); margin-bottom: var(--space-5); }
.ingredient-card {
  display: flex; align-items: center; gap: var(--space-3);
  background: var(--color-surface); border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md); padding: var(--space-3) var(--space-4);
}
.ingredient-info { flex: 1; display: flex; align-items: center; gap: var(--space-2); }
.ingredient-name-input {
  border: none; background: transparent; font-size: var(--text-base); font-weight: 600;
  color: var(--color-text-primary); width: 120px; outline: none;
  border-bottom: 1px solid transparent;
}
.ingredient-name-input:focus { border-bottom-color: var(--color-accent); }
.confidence { font-size: var(--text-xs); color: var(--color-text-tertiary); background: var(--color-surface); padding: 1px 6px; border-radius: 4px; }
.ingredient-weight { display: flex; align-items: center; gap: 4px; }
.weight-input {
  width: 70px; height: 36px; text-align: center; border: 1px solid var(--color-border);
  border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: var(--text-base);
  color: var(--color-text-primary); background: var(--color-surface); outline: none;
}
.weight-input:focus { border-color: var(--color-accent); }
.weight-unit { font-size: var(--text-sm); color: var(--color-text-tertiary); }
.remove-btn { background: none; border: none; font-size: 18px; color: var(--color-text-tertiary); cursor: pointer; padding: 4px; }
.remove-btn:hover { color: var(--color-danger); }

.confirm-actions { display: flex; gap: var(--space-3); flex-wrap: wrap; }

/* Result */
.result-header { margin-bottom: var(--space-6); }
.result-header h2 { font-size: var(--text-xl); font-weight: 700; margin-bottom: var(--space-2); }
.result-meta { display: flex; gap: var(--space-4); flex-wrap: wrap; }
.meta-item { font-size: var(--text-sm); color: var(--color-text-secondary); font-family: var(--font-mono); }

.recipe-cards { display: flex; flex-direction: column; gap: var(--space-4); margin-bottom: var(--space-6); }
.recipe-card {
  background: var(--color-surface); border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md); padding: var(--space-5);
}
.recipe-image-wrap {
  margin: calc(-1 * var(--space-5)) calc(-1 * var(--space-5)) var(--space-4) calc(-1 * var(--space-5));
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  overflow: hidden;
  height: 180px;
  background: var(--color-border-subtle);
}
.recipe-image {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.recipe-name { font-size: var(--text-md); font-weight: 700; margin-bottom: var(--space-2); }
.recipe-tags { display: flex; gap: var(--space-2); margin-bottom: var(--space-3); }
.recipe-tag { font-size: var(--text-xs); font-weight: 600; padding: 2px 8px; border-radius: var(--radius-sm); }
.recipe-tag--cal { background: var(--color-accent-subtle); color: var(--color-accent); }
.recipe-tag--pro { background: oklch(0.93 0.04 250); color: oklch(0.40 0.12 250); }
.recipe-tag--carb { background: oklch(0.93 0.04 80); color: oklch(0.45 0.12 80); }
.recipe-tag--fat { background: oklch(0.93 0.04 30); color: oklch(0.45 0.12 30); }
.recipe-ingredients { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-3); }
.recipe-ing { font-size: var(--text-xs); padding: 2px 8px; background: var(--color-surface); border: 1px solid var(--color-border-subtle); border-radius: var(--radius-sm); color: var(--color-text-secondary); }
.recipe-steps { font-size: var(--text-sm); color: var(--color-text-secondary); line-height: var(--leading-relaxed); }

.recipe-substitutes { margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px solid var(--color-border-subtle); }
.sub-title { font-size: var(--text-xs); font-weight: 700; color: var(--color-text-tertiary); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: var(--space-2); }
.sub-item { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-1); font-size: var(--text-sm); }
.sub-missing { color: var(--color-warning); font-weight: 600; }
.sub-arrow { color: var(--color-text-tertiary); }
.sub-alt { padding: 1px 6px; background: oklch(0.93 0.04 145); color: oklch(0.40 0.12 145); border-radius: var(--radius-sm); font-size: var(--text-xs); font-weight: 500; }

.recipe-shopping { margin-top: var(--space-2); font-size: var(--text-sm); }
.shopping-label { color: var(--color-text-tertiary); }
.shopping-item { display: inline-block; margin-left: var(--space-1); padding: 1px 6px; background: oklch(0.93 0.06 25); color: oklch(0.45 0.14 25); border-radius: var(--radius-sm); font-size: var(--text-xs); font-weight: 600; }

.full-recipe {
  background: var(--color-surface); border: 1px solid var(--color-border-subtle);
  border-radius: var(--radius-md); padding: var(--space-4) var(--space-5);
  margin-bottom: var(--space-6);
}
.full-recipe summary { cursor: pointer; font-weight: 600; color: var(--color-text-secondary); font-size: var(--text-sm); }
.full-recipe-content { margin-top: var(--space-4); font-size: var(--text-sm); line-height: var(--leading-relaxed); color: var(--color-text-primary); }
.full-recipe-content :deep(strong) { font-weight: 700; }

.result-actions { display: flex; gap: var(--space-3); }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; justify-content: center;
  height: 44px; padding: 0 var(--space-6); border-radius: var(--radius-sm);
  font-size: var(--text-base); font-weight: 600; font-family: var(--font-family);
  border: none; cursor: pointer; transition: all var(--duration-fast) var(--ease-out);
}
.btn-primary { background-color: var(--color-accent); color: white; }
.btn-primary:hover:not(:disabled) { background-color: var(--color-accent-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: var(--color-surface); color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-secondary:hover { border-color: var(--color-accent); color: var(--color-accent); }
.btn-ghost { background: transparent; color: var(--color-text-secondary); border: 1px solid var(--color-border); }
.btn-ghost:hover { border-color: var(--color-text-tertiary); }

@media (max-width: 480px) {
  .ingredient-card { flex-wrap: wrap; }
  .confirm-actions { flex-direction: column; }
  .result-actions { flex-direction: column; }
}
</style>
