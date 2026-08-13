import { describe, expect, it } from 'vitest'

import type { UserProfile } from '../types'
import { analyzeProfile } from './calc'

function makeProfile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    gender: 'male',
    age: 30,
    height: 175,
    weight: 80,
    target_weight: 70,
    target_weeks: null,
    activity_level: 'medium',
    diet_preference: 'balanced',
    goal_type: 'fat_loss',
    forbidden_foods: [],
    injuries: [],
    allergies: [],
    training_days_per_week: 3,
    session_duration_minutes: 60,
    training_location: 'gym',
    equipment: [],
    training_experience: 'beginner',
    preferred_training_time: 'evening',
    region_preference: 'balanced',
    meal_scenario: 'home_cooking',
    prep_time_limit_minutes: 30,
    ...overrides,
  }
}

describe('analyzeProfile', () => {
  it('uses the configured target period when one was supplied', () => {
    expect(analyzeProfile(makeProfile({ target_weeks: 6 })).estimatedWeeks).toBe(6)
  })

  it('uses the same low-carb macro strategy as the backend', () => {
    const result = analyzeProfile(makeProfile({ diet_preference: 'low_carb' }))
    const expectedCarbs = Math.max(Math.round(result.targetCalories * 0.2 / 4), 50)
    const expectedFat = Math.round(Math.max(
      result.targetCalories - result.proteinG * 4 - expectedCarbs * 4,
      0,
    ) / 9)

    expect(result.carbsG).toBe(expectedCarbs)
    expect(result.fatG).toBe(expectedFat)
  })
})
