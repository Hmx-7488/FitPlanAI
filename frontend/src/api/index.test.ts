import { beforeEach, describe, expect, it, vi } from 'vitest'

const { post, remove } = vi.hoisted(() => ({ post: vi.fn(), remove: vi.fn() }))

vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: vi.fn(),
      post,
      patch: vi.fn(),
      delete: remove,
    }),
  },
}))

import {
  applyCalorieAdjustment,
  applyWorkoutAdjustment,
  confirmIngredients,
  deletePoseAnalysis,
} from './index'

describe('API concurrency and ownership contracts', () => {
  beforeEach(() => {
    post.mockReset()
    post.mockResolvedValue({ data: {} })
    remove.mockReset()
    remove.mockResolvedValue({ data: {} })
  })

  it('sends the source plan and calorie baseline with an adjustment', async () => {
    await applyCalorieAdjustment(7, 23, 91, 1800, 1700)

    expect(post).toHaveBeenCalledWith('/plan/adjust-calories', {
      user_id: 7,
      plan_id: 23,
      source_checkin_id: 91,
      base_daily_calorie_target: 1800,
      daily_calorie_target: 1700,
    })
  })

  it('binds ingredient confirmation to the current user', async () => {
    await confirmIngredients(7, 42, [])

    expect(post).toHaveBeenCalledWith('/vision/confirm', {
      user_id: 7,
      recognition_id: 42,
      confirmed_ingredients: [],
    })
  })

  it('sends both source versions with a workout adjustment', async () => {
    await applyWorkoutAdjustment(7, 23, 91, '{"v":1}', '{"v":2}')

    expect(post).toHaveBeenCalledWith('/plan/adjust-workout', {
      user_id: 7,
      plan_id: 23,
      source_checkin_id: 91,
      base_workout_plan_json: '{"v":1}',
      adjusted_workout_plan_json: '{"v":2}',
    })
  })

  it('uses the owned pose deletion endpoint', async () => {
    await deletePoseAnalysis(7, 'pose_abc')
    expect(remove).toHaveBeenCalledWith('/pose/history/7/pose_abc')
  })
})
