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
  streamChatMessage,
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

describe('chat tool event stream', () => {
  it('dispatches bounded tool trace events separately from answer deltas', async () => {
    const payload = [
      'event: meta\ndata: {"tool_call_count":1}\n\n',
      'event: tool\ndata: {"call_id":"call-plan","tool_name":"get_latest_plan"}\n\n',
      'event: delta\ndata: {"content":"1900 千卡"}\n\n',
      'event: done\ndata: {"id":7}\n\n',
    ].join('')
    const response = new Response(payload, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const onTool = vi.fn()
    const onDelta = vi.fn()

    await streamChatMessage(
      3,
      { user_id: 1, content: '我的热量目标是多少' },
      { onTool, onDelta }
    )

    expect(onTool).toHaveBeenCalledWith({
      call_id: 'call-plan',
      tool_name: 'get_latest_plan',
    })
    expect(onDelta).toHaveBeenCalledWith('1900 千卡')
    vi.unstubAllGlobals()
  })
})
