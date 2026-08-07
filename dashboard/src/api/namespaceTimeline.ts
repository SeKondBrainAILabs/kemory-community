import { api } from './client'

export type TimelineKind = 'chat' | 'memory'

export interface TimelineEntry {
  kind: TimelineKind
  id: string
  occurred_at: string
  namespace: string
  platform: string
  title?: string | null
  turn_count?: number | null
  artifact_count?: number | null
  memory_count?: number | null
  preview?: string | null
  memory_type?: string | null
  source_chat_id?: string | null
  source_turn_id?: string | null
}

export interface TimelineResponse {
  namespace: string
  items: TimelineEntry[]
  limit: number
  has_more: boolean
  next_cursor: string | null
}

export interface TimelineParams {
  namespace: string
  types?: TimelineKind[]
  cursor?: string
  limit?: number
}

export async function listNamespaceTimeline(params: TimelineParams): Promise<TimelineResponse> {
  const search: Record<string, string | number> = { limit: params.limit ?? 40 }
  if (params.types?.length) search.types = params.types.join(',')
  if (params.cursor) search.cursor = params.cursor
  return api
    .get(`api/v1/namespaces/${encodeURIComponent(params.namespace)}/timeline`, {
      searchParams: search,
    })
    .json()
}
