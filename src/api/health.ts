import { api } from './client'
import type { DeepHealthResponse, LivenessResponse } from './types'

export async function getLiveness(): Promise<LivenessResponse> {
  return api.get('health/live').json()
}

export async function getDeepHealth(): Promise<DeepHealthResponse> {
  return api.get('health/deep').json()
}
