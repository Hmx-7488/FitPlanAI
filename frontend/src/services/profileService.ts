import { createProfile, updateProfile } from '../api'
import type { UserProfile, UserProfileResponse } from '../types'

export async function saveProfile(
  profileLoaded: boolean,
  storedUserId: number,
  profile: UserProfile,
): Promise<UserProfileResponse> {
  if (!profileLoaded) {
    return createProfile(profile)
  }
  if (!Number.isInteger(storedUserId) || storedUserId <= 0) {
    throw new Error('Existing profile is missing a valid user id')
  }
  return updateProfile(storedUserId, profile)
}
