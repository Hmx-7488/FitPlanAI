export interface UserProfile {
  gender: 'male' | 'female'
  age: number
  height: number
  weight: number
  target_weight: number
  activity_level: 'low' | 'medium' | 'high' | 'very_high'
  diet_preference: 'balanced' | 'high_protein' | 'low_carb' | 'vegetarian'
  forbidden_foods: string[]
}

export interface UserProfileResponse extends UserProfile {
  id: number
}

export interface CalorieInfo {
  bmr: number
  tdee: number
  target_calories: number
  deficit: number
}

export interface MacrosInfo {
  protein_g: number
  carbs_g: number
  fat_g: number
  fiber_g: number
  water_ml: number
}

export interface PlanResponse {
  id: number
  user_id: number
  daily_calorie_target: number
  calorie_info: CalorieInfo
  macros: MacrosInfo
  meal_plan: string
  workout_plan: string
  summary: string
}

// 打卡相关
export interface CheckinData {
  user_id: number
  date: string
  foods: string
  exercises: string
  weight?: number
  note: string
}

export interface CheckinResponse {
  id: number
  user_id: number
  date: string
  foods: string
  exercises: string
  weight: number | null
  note: string
  feedback?: string
}

export interface ReviewResponse {
  user_id: number
  checkin_count: number
  recent_checkins: CheckinResponse[]
  review_summary: string
  next_day_advice: string
}
