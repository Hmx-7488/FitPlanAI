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
  target_weeks?: number | null
  body_fat_rate?: number | null
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
  meal_plan_json?: string | null
  workout_plan: string
  workout_plan_json?: string | null
  supplements_json?: string | null
  summary: string
  created_at?: string
}

export interface WorkoutAdjustRequest {
  user_id: number
  plan_id: number
  source_checkin_id: number
  base_workout_plan_json: string
  adjusted_workout_plan_json: string
}

export interface WorkoutExercise {
  exercise_id: string
  sets: number
  reps: string
  rest_seconds: number
  _flagged_for_replacement?: string
}

export interface WorkoutDay {
  day: number
  theme: string
  duration_minutes: number
  exercises: WorkoutExercise[]
  cardio?: { type: string; duration_minutes: number; intensity: string }
}

export interface StructuredWorkoutPlan {
  excluded: { exercise_id: string; reason: string }[]
  weekly_plan: WorkoutDay[]
  warmup: string[]
  notes: string[]
}

export interface MealItem {
  food_id: number
  name: string
  portion_g: number
  calories: number
  protein_g: number
  carbs_g: number
  fat_g: number
  is_from_database: boolean
}

export interface MealBlock {
  meal_type: string
  items: MealItem[]
  meal_total: { calories: number; protein_g: number; carbs_g: number; fat_g: number }
}

export interface StructuredMealPlan {
  meals: MealBlock[]
  daily_total: { calories: number; protein_g: number; carbs_g: number; fat_g: number }
  target_match: {
    protein_pct: number
    carbs_pct: number
    fat_pct: number
    calories_pct: number
  }
  snack_suggestion?: string
  tips?: string[]
}

// 补剂推荐
export interface SupplementRecommendation {
  name: string
  name_en: string
  reason: string
  dosage: string
  timing: string
  contraindications: string[]
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

export interface CalorieAdjustment {
  current_target: number
  suggested_target: number
  delta_kcal: number
  weekly_change_pct: number
  reason: string
  basis: string
}

export interface WorkoutAdjustmentChange {
  day: string
  action: string
  old_exercise_keyword?: string
  detail?: string
  reason: string
}

export interface WorkoutAdjustment {
  reason: string
  changes: WorkoutAdjustmentChange[]
  risk_notes: string[]
}

export interface ReviewResponse {
  user_id: number
  source_plan_id: number | null
  source_daily_calorie_target: number | null
  source_workout_plan_json: string | null
  source_checkin_id: number
  checkin_count: number
  recent_checkins: CheckinResponse[]
  review_summary: string
  next_day_advice: string
  calorie_adjustment?: CalorieAdjustment | null
  workout_adjustment?: WorkoutAdjustment | null
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
  user_id: number
  recognition_id: number
  confirmed_ingredients: IngredientItem[]
}

export interface RecipeImage {
  url: string
  alt: string
  generation_prompt: string
  status?: string
  model?: string
  error_message?: string
  retry_count?: number
  cache_hit?: boolean
}

export interface RecipeImageJob {
  id: number
  recipe_id: number
  recipe_index: number
  status: 'queued' | 'generating' | 'ready' | 'failed'
  image_url: string
  model: string
  error_code: string
  error_message: string
  retry_count: number
  cache_hit: boolean
  updated_at?: string
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
  status: 'completed' | 'rejected' | 'fallback'
  created_at?: string
  photo_url?: string
  photo_urls?: Record<string, string>
  measurements?: BodyMeasurements
  quality_check: {
    is_usable: boolean
    usable_views: string[]
    views: Record<string, BodyViewQuality>
    rejection_reasons: string[]
    retake_guidance: string[]
  }
  body_fat_estimate: {
    value?: number | null
    estimated_range: string
    confidence: number
    note?: string
    sources?: BodyEstimateSource[]
  }
  tracking_metrics?: Record<string, number>
  training_focus: string[]
  nutrition_suggestion: string
  limitations?: string[]
  comparison?: BodyComparison | null
  auto_filled?: boolean
  is_ai_analysis?: boolean
}

export interface BodyMeasurements {
  waist_cm?: number
  hip_cm?: number
  chest_cm?: number
  neck_cm?: number
  body_fat_scale_pct?: number
  measured_weight_kg?: number
}

export interface BodyViewQuality {
  usable: boolean
  correct_view: boolean
  full_body_visible: boolean
  torso_visible: boolean
  lighting: string
  clothing: string
  occlusion: string
  camera_level: string
  issues: string[]
}

export interface BodyEstimateSource {
  key: string
  label: string
  value: number
  weight: number
}

export interface BodyComparison {
  is_comparable: boolean
  confidence?: number
  comparable_views: string[]
  summary: string
  changes?: string[]
  limitations?: string[]
  previous_analysis_id?: string
  previous_created_at?: string
  measurement_changes?: Record<string, number>
}

export interface BodyAnalysisHistoryItem {
  analysis_id: string
  status: BodyPhotoAnalysis['status']
  created_at: string
  photo_urls: Record<string, string>
  measurements: BodyMeasurements
  quality_check: BodyPhotoAnalysis['quality_check']
  body_fat_estimate: BodyPhotoAnalysis['body_fat_estimate'] | null
  comparison?: BodyComparison | null
  confidence: number
  is_ai_analysis: boolean
}

// AI 动作分析
export interface PoseMetric {
  name: string
  score: number
  description: string
  source?: 'keypoints' | 'vision'
}

export interface PoseIssue {
  title: string
  severity: 'high' | 'medium' | 'low'
  description: string
  timestamp?: number | null
  impact: string
  correction: string
}

export interface PoseCorrection {
  area: string
  technique: string
  drills: string[]
  sets_reps: string
  next_filming_tip: string
}

export interface PosePhase {
  phase: string
  observation: string
}

export interface PoseAnalysis {
  analysis_id: string
  movement_name: string
  overall_score: number
  risk_level: 'low' | 'medium' | 'high'
  summary: string
  confidence: number
  photo_url?: string
  video_url?: string
  frame_urls?: string[]
  media_type?: 'image' | 'video'
  rep_count_estimate?: number | null
  analyzed_frames?: number
  metrics: PoseMetric[]
  issues: PoseIssue[]
  corrections: PoseCorrection[]
  good_points: string[]
  phases?: PosePhase[]
  coach_cues: string[]
  risk_warnings?: string[]
  is_ai_analysis?: boolean
  is_quantitative_analysis?: boolean
  analysis_source?: 'hybrid' | 'keypoint_only' | 'vision_only' | 'template' | 'rejected'
  analysis_status?: 'completed' | 'fallback' | 'rejected'
  pose_quality?: {
    is_usable: boolean
    average_visibility: number
    usable_frame_ratio: number
    edge_frame_ratio: number
    issues: string[]
    confidence: number
  } | null
  joint_angles?: Record<string, {
    min: number
    max: number
    range: number
    mean: number
  }>
  /** @deprecated 使用 overall_score */
  score?: number
}

// 餐食热量识别
export interface MealRecognitionItem {
  dish_name: string
  estimated_portion_g: number
  calories_kcal: number
  protein_g: number
  carbs_g: number
  fat_g: number
  confidence?: number
  need_confirm?: boolean
  is_from_database?: boolean
  data_source?: string
  matched_food_id?: number
  matched_food_name?: string
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
  items: MealRecognitionItem[]
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
    items: MealRecognitionItem[]
    meal_total: MealAnalysis['meal_total']
    created_at?: string
  } | null>
}

export interface ChatCitation {
  chunk_id: string
  title: string
  category: string
  source_name: string
  source_url: string
  evidence_level: string
  score: number
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  citations: ChatCitation[]
  context: Record<string, unknown>
  status: string
  created_at: string
}

export interface ChatConversation {
  id: number
  user_id: number
  title: string
  status: string
  created_at: string
  updated_at: string
  last_message: string
}

export interface ChatConversationDetail extends ChatConversation {
  messages: ChatMessage[]
}

export type UserMemoryType = 'preference' | 'goal' | 'habit' | 'constraint' | 'experience'
export type UserMemoryStatus = 'candidate' | 'confirmed' | 'rejected'

export interface UserMemory {
  id: number
  user_id: number
  memory_type: UserMemoryType
  memory_key: string
  content: Record<string, unknown>
  content_text: string
  source_conversation_id: number | null
  source_message_id: number | null
  confirmation_status: UserMemoryStatus
  sensitivity: 'normal' | 'health_sensitive'
  confidence: number
  valid_from: string
  valid_until: string | null
  supersedes_memory_id: number | null
  created_by: string
  created_at: string
  updated_at: string
}
