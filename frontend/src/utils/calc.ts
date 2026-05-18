import type { UserProfile, GoalType } from '../types'

export interface AnalysisResult {
  bmi: number
  bmiCategory: string
  bmr: number
  tdee: number
  targetCalories: number
  deficit: number
  proteinG: number
  carbsG: number
  fatG: number
  fiberG: number
  waterMl: number
  weightToLose: number
  estimatedWeeks: number
  activityLabel: string
  dietLabel: string
  goalType: GoalType
}

const ACTIVITY_LABELS: Record<string, string> = {
  low: '久坐',
  medium: '轻度活动',
  high: '高度活动',
  very_high: '极高活动',
}

const DIET_LABELS: Record<string, string> = {
  balanced: '均衡饮食',
  high_protein: '高蛋白',
  low_carb: '低碳水',
  vegetarian: '素食',
}

function calcBmi(weight: number, heightCm: number): number {
  const heightM = heightCm / 100
  return +(weight / (heightM * heightM)).toFixed(1)
}

function bmiCategory(bmi: number): string {
  if (bmi < 18.5) return '偏瘦'
  if (bmi < 24) return '正常'
  if (bmi < 28) return '偏胖'
  return '肥胖'
}

/** Mifflin-St Jeor */
function calcBmr(gender: string, weight: number, height: number, age: number): number {
  const base = 10 * weight + 6.25 * height - 5 * age
  return gender === 'male' ? base + 5 : base - 161
}

const ACTIVITY_MULTIPLIERS: Record<string, number> = {
  low: 1.2,
  medium: 1.55,
  high: 1.725,
  very_high: 1.9,
}

function calcTdee(bmr: number, activityLevel: string): number {
  return bmr * (ACTIVITY_MULTIPLIERS[activityLevel] ?? 1.55)
}

function calcTargetCalories(tdee: number, goalType: GoalType = 'fat_loss'): number {
  if (goalType === 'muscle_gain') {
    // 增肌：TDEE 增加 5%-15%
    return Math.round(tdee * 1.10)
  }
  // 减脂：TDEE 减少 10%-25%
  const target = tdee * 0.8 // 20% deficit
  return Math.max(Math.round(target), 1200)
}

function calcMacros(targetCalories: number, weight: number, activityLevel: string, goalType: GoalType = 'fat_loss') {
  let proteinPerKg: number
  if (goalType === 'muscle_gain') {
    proteinPerKg = activityLevel === 'high' || activityLevel === 'very_high' ? 2.2 : 1.8
  } else {
    proteinPerKg = activityLevel === 'high' || activityLevel === 'very_high' ? 2.0 : 1.6
  }
  const proteinG = Math.round(weight * proteinPerKg)
  const proteinCal = proteinG * 4

  const fatCal = targetCalories * 0.25
  const fatG = Math.round(fatCal / 9)

  const carbCal = targetCalories - proteinCal - fatCal
  const carbsG = Math.max(Math.round(carbCal / 4), 50)

  return {
    proteinG,
    carbsG,
    fatG,
    fiberG: 25,
    waterMl: Math.round(weight * 35),
  }
}

/** 安全减重速度：每周 0.5-1kg，取 0.7kg */
function estimateWeeks(weightToLose: number): number {
  if (weightToLose <= 0) return 0
  return Math.ceil(weightToLose / 0.7)
}

export function analyzeProfile(profile: UserProfile): AnalysisResult {
  const goalType = profile.goal_type || 'fat_loss'
  const bmi = calcBmi(profile.weight, profile.height)
  const bmr = Math.round(calcBmr(profile.gender, profile.weight, profile.height, profile.age))
  const tdee = Math.round(calcTdee(bmr, profile.activity_level))
  const targetCalories = calcTargetCalories(tdee, goalType)
  const deficit = goalType === 'muscle_gain'
    ? targetCalories - tdee  // 增肌：盈余为正数
    : tdee - targetCalories  // 减脂：缺口为正数
  const macros = calcMacros(targetCalories, profile.weight, profile.activity_level, goalType)
  const weightToLose = +(profile.weight - profile.target_weight).toFixed(1)
  const estimatedWeeks = estimateWeeks(weightToLose)

  return {
    bmi,
    bmiCategory: bmiCategory(bmi),
    bmr,
    tdee,
    targetCalories,
    deficit,
    ...macros,
    weightToLose,
    estimatedWeeks,
    activityLabel: ACTIVITY_LABELS[profile.activity_level] ?? profile.activity_level,
    dietLabel: DIET_LABELS[profile.diet_preference] ?? profile.diet_preference,
    goalType,
  }
}
