import axios from 'axios'
import type {
  UserProfile,
  UserProfileResponse,
  PlanResponse,
  CheckinData,
  CheckinResponse,
  ReviewResponse,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
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
