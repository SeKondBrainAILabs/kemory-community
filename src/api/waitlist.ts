import { api } from './client'

export interface WaitlistEntry {
  id: string
  user_id: string
  email: string
  display_name: string | null
  service: string
  status: string
  position: number
  referral_code: string
  referred_by_code: string | null
  referral_count: number
  joined_at: string | null
  approved_at: string | null
  source: string | null
}

export interface WaitlistListResponse {
  entries: WaitlistEntry[]
  total: number
  limit: number
  offset: number
}

export interface WaitlistStats {
  total: number
  pending: number
  approved: number
  rejected: number
  conversion_rate: number
  total_referrals: number
  top_referrers: { name: string; count: number }[]
}

export async function fetchWaitlistEntries(params: {
  service?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<WaitlistListResponse> {
  const sp = new URLSearchParams()
  if (params.service) sp.set('service', params.service)
  if (params.status) sp.set('status', params.status)
  if (params.limit) sp.set('limit', String(params.limit))
  if (params.offset) sp.set('offset', String(params.offset))
  return api.get(`api/v1/admin/waitlist?${sp}`).json()
}

export async function fetchWaitlistStats(
  service?: string,
): Promise<WaitlistStats> {
  const sp = service ? `?service=${service}` : ''
  return api.get(`api/v1/admin/waitlist/stats${sp}`).json()
}

export async function approveUser(
  userId: string,
  service = 'memory_vault',
): Promise<{ approved: boolean }> {
  return api
    .post(`api/v1/admin/waitlist/${userId}/approve?service=${service}`)
    .json()
}

export async function rejectUser(
  userId: string,
  service = 'memory_vault',
): Promise<{ rejected: boolean }> {
  return api
    .post(`api/v1/admin/waitlist/${userId}/reject?service=${service}`)
    .json()
}

export async function bulkApprove(
  userIds: string[],
  service = 'memory_vault',
): Promise<{ approved_count: number }> {
  return api
    .post('api/v1/admin/waitlist/bulk-approve', {
      json: { user_ids: userIds, service },
    })
    .json()
}
