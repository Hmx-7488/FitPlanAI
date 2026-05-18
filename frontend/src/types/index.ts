export type GoalType = 'fat_loss' | 'muscle_gain'

export interface UserProfile {
  gender: 'male' | 'female'
  age: number
  height: number
  weight: number
  target_weight: number
  body_fat_rate?: number
  activity_level: 'low' | 'medium' | 'high' | 'very_high'
  diet_preference: 'balanced' | 'high_protein' | 'low_carb' | 'vegetarian'
  goal_type: GoalType
  forbidden_foods: string[]
  injuries: string[]
  allergies: string[]
}

export interface UserProfileResponse extends UserProfile {
  id: number
}

export interface CalorieInfo {
  bmr: number
  tdee: number
  target_calories: number
  deficit: number
  goal_type: GoalType
  strategy: string
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
  created_at?: string
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

// Agent 追问响应
export interface NeedInfoResponse {
  status: 'need_info'
  missing_fields: string[]
  field_warnings: string[]
  followup_questions: string
}

// 食材识别
export interface IngredientItem {
  name: string
  display_name: string
  estimated_weight_g: number
  confidence: number
  need_confirm: boolean
}

export interface RecognizeResponse {
  recognition_id: number
  ingredients: IngredientItem[]
  question_to_user: string
}

export interface ConfirmRequest {
  recognition_id: number
  confirmed_ingredients: IngredientItem[]
}

export interface RecipeImage {
  url: string
  alt: string
  generation_prompt: string
}

export interface RecipeItem {
  name: string
  ingredients: string[]
  calories_est: number
  protein_est: number
  carbs_est: number
  fat_est: number
  steps: string
  image: RecipeImage
}

export interface RecipeResponse {
  recipe_id: number
  user_id: number
  recognition_id: number
  recipes: RecipeItem[]
  total_calories: number
  total_protein: number
  recipe_content: string
  created_at?: string
}
