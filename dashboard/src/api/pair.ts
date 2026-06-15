import { api } from './client'

export interface PairStartResponse {
  code: string
  claim_url: string
  expires_in: number
}

export interface PairStatusResponse {
  code: string
  claimed: boolean
  expires_in: number
  agent_id?: string
  agent_name?: string
  client_name?: string
}

export async function startPair(purpose = ''): Promise<PairStartResponse> {
  return api.post('api/v1/pair/start', { json: { purpose } }).json()
}

export async function getPairStatus(code: string): Promise<PairStatusResponse> {
  return api.get(`api/v1/pair/${code}/status`).json()
}
