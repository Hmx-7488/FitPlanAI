import axios from 'axios'
import type {
  UserProfile,
  UserProfileResponse,
  PlanResponse,
  CheckinData,
  CheckinResponse,
  ReviewResponse,
  RecognizeResponse,
  ConfirmRequest,
  RecipeResponse,
  IngredientItem,
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
