import axios from 'axios'
import type {
  UserProfile,
  UserProfileResponse,
  PlanResponse,
  CheckinData,
  CheckinResponse,
  ReviewResponse,
  RecognizeResponse,
  RecipeResponse,
  IngredientItem,
  MealItem,
  MealAnalysis,
  MealDailySummary,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000,
})

// 用户档案
export async function createProfile(data: UserProfile): Promise<UserProfileResponse> {
  const res = await api.post<UserProfileResponse>('/profile/create', data)
  return res.data
}

export async function getProfile(userId: number): Promise<UserProfileResponse> {
  const res = await api.get<UserProfileResponse>(`/profile/${userId}`)
  return res.data
}

export async function updateProfile(userId: number, data: Partial<UserProfile>): Promise<UserProfileResponse> {
  const res = await api.patch<UserProfileResponse>(`/profile/${userId}`, data)
  return res.data
}

export async function estimateBodyFat(userId: number, imageFile: File) {
  const formData = new FormData()
  formData.append('image', imageFile)
  const res = await api.post(`/profile/${userId}/estimate-body-fat`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return res.data as {
    photo_url: string
    body_fat_estimate: number
    body_fat_range: string
    training_focus: string[]
    nutrition_suggestion: string
    note: string
    auto_filled: boolean
  }
}

// 减脂计划
export async function getLatestPlan(userId: number): Promise<PlanResponse | null> {
  const res = await api.get<PlanResponse | null>(`/plan/latest/${userId}`)
  return res.data
}

export async function generatePlan(userId: number): Promise<PlanResponse> {
  const res = await api.post<PlanResponse>('/plan/generate', { user_id: userId })
  return res.data
}

// 每日打卡
export async function createCheckin(data: CheckinData): Promise<CheckinResponse> {
  const res = await api.post<CheckinResponse>('/checkin/create', data)
  return res.data
}

export async function getCheckinHistory(
  userId: number,
  limit: number = 7
): Promise<CheckinResponse[]> {
  const res = await api.get<CheckinResponse[]>(
    `/checkin/history/${userId}?limit=${limit}`
  )
  return res.data
}

// 复盘与调整
export async function getReview(userId: number): Promise<ReviewResponse> {
  const res = await api.get<ReviewResponse>(`/checkin/review/${userId}`)
  return res.data
}

// 食材识别
export async function recognizeIngredients(
  userId: number,
  imageFile: File
): Promise<RecognizeResponse> {
  const formData = new FormData()
  formData.append('user_id', String(userId))
  formData.append('image', imageFile)
  const res = await api.post<RecognizeResponse>('/vision/recognize', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return res.data
}

export async function confirmIngredients(
  recognitionId: number,
  confirmedIngredients: IngredientItem[]
): Promise<{ recognition_id: number; status: string }> {
  const res = await api.post('/vision/confirm', {
    recognition_id: recognitionId,
    confirmed_ingredients: confirmedIngredients,
  })
  return res.data
}

export async function generateRecipes(
  userId: number,
  recognitionId: number,
  confirmedIngredients: IngredientItem[]
): Promise<RecipeResponse> {
  const res = await api.post<RecipeResponse>('/vision/recipes', {
    user_id: userId,
    recognition_id: recognitionId,
    confirmed_ingredients: confirmedIngredients,
  })
  return res.data
}

export async function getLatestRecipe(userId: number): Promise<RecipeResponse | null> {
  try {
    const res = await api.get<RecipeResponse | null>(`/vision/recipes/latest/${userId}`)
    return res.data
  } catch {
    return null
  }
}

// Dashboard 聚合数据
export interface DashboardData {
  profile: {
    id: number
    gender: string
    age: number
    height: number
    weight: number
    target_weight: number
    goal_type: string
    body_fat_rate?: number
  }
  latest_plan: {
    id: number
    daily_calorie_target: number
    protein_g: number
    carbs_g: number
    fat_g: number
    summary: string
    created_at?: string
  } | null
  meal_summary: {
    date: string
    target_kcal: number
    consumed_kcal: number
    remaining_kcal: number
    progress_pct: number
    meal_count: number
    consumed_protein: number
    consumed_carbs: number
    consumed_fat: number
  }
  checkin_summary: {
    streak: number
    total_days: number
    latest_weight: number
    weight_change: number
    today_checked: boolean
  }
}

export async function getDashboard(userId: number): Promise<DashboardData> {
  const res = await api.get<DashboardData>(`/dashboard/${userId}`)
  return res.data
}

// 身材照片分析
export async function analyzeBodyPhoto(userId: number, imageFile: File | { front?: File | null; side?: File | null; back?: File | null }) {
  const formData = new FormData()
  formData.append('user_id', String(userId))
  if (imageFile instanceof File) {
    formData.append('image', imageFile)
  } else {
    if (imageFile.front) formData.append('front_image', imageFile.front)
    if (imageFile.side) formData.append('side_image', imageFile.side)
    if (imageFile.back) formData.append('back_image', imageFile.back)
  }
  const res = await api.post('/body/analyze', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
  return res.data
}

// AI 动作分析
export async function analyzePose(userId: number, imageFile: File, movementName: string) {
  const formData = new FormData()
  formData.append('user_id', String(userId))
  formData.append('image', imageFile)
  formData.append('movement_name', movementName)
  const res = await api.post('/pose/analyze', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}

export async function analyzePoseVideo(userId: number, videoFile: File, frames: File[], movementName: string) {
  const formData = new FormData()
  formData.append('user_id', String(userId))
  formData.append('video', videoFile)
  formData.append('movement_name', movementName)
  frames.forEach((frame, index) => {
    formData.append('frames', frame, `frame_${index}.jpg`)
  })
  const res = await api.post('/pose/analyze-video', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  })
  return res.data
}

// 餐食识别（新流程）
export interface MealRecognizeResponse {
  recognition_id: string
  ingredients: Array<{
    name: string
    display_name: string
    estimated_weight_g: number
    confidence: number
  }>
}

export interface MealCalculateRequest {
  recognition_id: string
  ingredients: Array<{
    name: string
    display_name: string
    estimated_weight_g: number
    confidence?: number
  }>
  meal_type: string
}

// MealAnalysis、MealDailySummary 统一从 types 导入
export type { MealAnalysis, MealDailySummary, MealItem }

export async function recognizeMeal(
  userId: number,
  imageFile: File,
  mealType: string = 'lunch'
): Promise<MealRecognizeResponse> {
  const formData = new FormData()
  formData.append('user_id', String(userId))
  formData.append('meal_type', mealType)
  formData.append('image', imageFile)
  const res = await api.post<MealRecognizeResponse>('/meal/recognize', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return res.data
}

export async function calculateMeal(
  data: MealCalculateRequest
): Promise<MealAnalysis> {
  const res = await api.post<MealAnalysis>('/meal/calculate', data, {
    timeout: 120000,
  })
  return res.data
}

export async function getMealDailySummary(userId: number, date?: string): Promise<MealDailySummary> {
  const query = date ? `?date=${encodeURIComponent(date)}` : ''
  const res = await api.get<MealDailySummary>(`/meal/daily-summary/${userId}${query}`)
  return res.data
}
