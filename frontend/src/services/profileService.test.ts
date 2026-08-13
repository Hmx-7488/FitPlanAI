import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UserProfile } from '../types'

const { createProfile, updateProfile } = vi.hoisted(() => ({
  createProfile: vi.fn(),
  updateProfile: vi.fn(),
}))

vi.mock('../api', () => ({ createProfile, updateProfile }))

import { saveProfile } from './profileService'

const profile = {} as UserProfile

describe('saveProfile', () => {
  beforeEach(() => {
    createProfile.mockReset()
    updateProfile.mockReset()
  })

  it('patches an existing profile without creating a second user', async () => {
    updateProfile.mockResolvedValue({ id: 11 })

    await saveProfile(true, 11, profile)

    expect(updateProfile).toHaveBeenCalledWith(11, profile)
    expect(createProfile).not.toHaveBeenCalled()
  })

  it('creates only when the page is in first-profile mode', async () => {
    createProfile.mockResolvedValue({ id: 12 })

    await saveProfile(false, Number.NaN, profile)

    expect(createProfile).toHaveBeenCalledWith(profile)
    expect(updateProfile).not.toHaveBeenCalled()
  })

  it('does not silently create when an existing profile loses its id', async () => {
    await expect(saveProfile(true, Number.NaN, profile)).rejects.toThrow()
    expect(createProfile).not.toHaveBeenCalled()
  })
})
