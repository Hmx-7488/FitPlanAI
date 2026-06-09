export type GoalType = 'fat_loss' | 'muscle_gain'

export type TrainingLocation = 'gym' | 'home' | 'outdoor'
export type TrainingExperience = 'beginner' | 'intermediate' | 'advanced'
export type PreferredTrainingTime = 'morning' | 'afternoon' | 'evening'
export type RegionPreference = 'south_china' | 'north_china' | 'sichuan' | 'cantonese' | 'balanced'
export type MealScenario = 'home_cooking' | 'takeout' | 'canteen' | 'convenience_store'

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
  // 训练条件
  training_days_per_week: number
  session_duration_minutes: number
  training_location: TrainingLocation
  equipment: string[]
  training_experience: TrainingExperience
  preferred_training_time: PreferredTrainingTime
  // 中国饮食习惯
  region_preference: RegionPreference
  meal_scenario: MealScenario
  prep_time_limit_minutes: number
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
  status?: string
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
  missing_ingredients: string[]
  substitute_ingredients: { missing: string; alternatives: string[] }[]
  shopping_list: string[]
}

export interface RecipeResponse {
  recipe_id: number
  user_id: number
  recognition_id: number
  food_image_url?: string
  recipes: RecipeItem[]
  total_calories: number
  total_protein: number
  recipe_content: string
  created_at?: string
}

// 身材照片分析
export interface BodyPhotoAnalysis {
  analysis_id: string
  photo_url?: string
  photo_urls?: Record<string, string>
  quality_check: {
    is_usable: boolean
    lighting: string
    pose: string
    visible_body_regions?: string[]
  }
  body_fat_estimate: {
    estimated_range: string
    confidence: number
    note?: string
  }
  training_focus: string[]
  nutrition_suggestion: string
  auto_filled?: boolean
  is_ai_analysis?: boolean
}

// AI 动作分析
export interface PoseAnalysis {
  analysis_id: string
  movement_name: string
  score: number
  photo_url?: string
  video_url?: string
  frame_urls?: string[]
  media_type?: 'image' | 'video'
  rep_count_estimate?: number | null
  phases?: {
    phase: string
    observation: string
  }[]
  issues: {
    type: string
    severity: string
    description: string
    suggestion: string
  }[]
  coach_cues: string[]
  risk_warnings?: string[]
  is_ai_analysis?: boolean
}

// 餐食热量识别
export interface MealItem {
  dish_name: string
  estimated_portion_g: number
  calories_kcal: number
  protein_g: number
  carbs_g: number
  fat_g: number
  confidence?: number
  need_confirm?: boolean
}

export interface DailySummary {
  daily_target_kcal: number
  estimated_tdee_kcal: number
  consumed_kcal: number
  remaining_target_kcal: number
  current_deficit_kcal: number
  status: string
  suggestion: string
}

export interface MealAnalysis {
  meal_type: string
  items: MealItem[]
  meal_total: {
    calories_kcal: number
    protein_g: number
    carbs_g: number
    fat_g: number
  }
  daily_summary: DailySummary
  question_to_user?: string
}

export interface MealDailySummary {
  date: string
  meal_count: number
  daily_target_kcal: number
  estimated_tdee_kcal: number
  consumed_kcal: number
  remaining_target_kcal: number
  current_deficit_kcal: number
  progress_pct: number
  status: string
  suggestion: string
  consumed: {
    calories_kcal: number
    protein_g: number
    carbs_g: number
    fat_g: number
  }
  meals: Record<string, {
    id: number
    meal_type: string
    image_url: string
    items: MealItem[]
    meal_total: MealAnalysis['meal_total']
    created_at?: string
  } | null>
}
