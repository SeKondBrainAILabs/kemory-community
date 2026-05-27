/**
 * Kemory dashboard — Artifacts API client (project files — v3.35.0).
 *
 * Covers the namespace-level and memory-level artifact endpoints
 * introduced in v3.35.0. Chat-turn artifacts are still accessed via
 * the chats API (GET /api/v1/chats/{id}?include=artifacts).
 *
 * Backend reference: backend/api/routes/artifacts.py
 */
import { api } from './client'
import type { ArtifactResponse } from './chats'

// ─── Re-export so callers can import from one place ────────────────
export type { ArtifactResponse }

// ─── List ──────────────────────────────────────────────────────────

export interface ArtifactListResponse {
  items: ArtifactResponse[]
  total: number
  limit: number
  offset: number
}

export async function listNamespaceArtifacts(
  namespace: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ArtifactListResponse> {
  const search: Record<string, number> = {}
  search.limit = params.limit ?? 50
  search.offset = params.offset ?? 0
  return api
    .get(`api/v1/namespaces/${encodeURIComponent(namespace)}/artifacts`, {
      searchParams: search,
    })
    .json()
}

export async function listMemoryArtifacts(memoryId: string): Promise<ArtifactResponse[]> {
  return api.get(`api/v1/memories/${encodeURIComponent(memoryId)}/artifacts`).json()
}

// ─── Get single ────────────────────────────────────────────────────

export async function getArtifact(artifactId: string): Promise<ArtifactResponse> {
  return api.get(`api/v1/artifacts/${encodeURIComponent(artifactId)}`).json()
}

// ─── Upload ────────────────────────────────────────────────────────

export interface UploadArtifactParams {
  file: File
  /** Explicit namespace; OR provide platform + projectId. */
  namespace?: string
  platform?: string
  projectId?: string
  projectName?: string
  /** Attach to a memory by UUID. */
  memoryId?: string
  artifactType?: string
  language?: string
}

export async function uploadArtifact(
  params: UploadArtifactParams,
): Promise<ArtifactResponse> {
  const form = new FormData()
  form.append('file', params.file, params.file.name)
  if (params.namespace) form.append('namespace', params.namespace)
  if (params.platform) form.append('platform', params.platform)
  if (params.projectId) form.append('project_id', params.projectId)
  if (params.projectName) form.append('project_name', params.projectName)
  if (params.memoryId) form.append('memory_id', params.memoryId)
  if (params.artifactType) form.append('artifact_type', params.artifactType)
  if (params.language) form.append('language', params.language)

  return api
    .post('api/v1/artifacts/upload', { body: form })
    .json()
}

export async function uploadMemoryArtifact(
  memoryId: string,
  file: File,
): Promise<ArtifactResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  return api
    .post(`api/v1/memories/${encodeURIComponent(memoryId)}/artifacts/upload`, { body: form })
    .json()
}

// ─── Delete ────────────────────────────────────────────────────────

export async function deleteArtifact(artifactId: string): Promise<void> {
  await api.delete(`api/v1/artifacts/${encodeURIComponent(artifactId)}`)
}

// ─── Helpers ───────────────────────────────────────────────────────

/** Human-readable file size string. */
export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Pick a lucide icon name for an artifact type. */
export function artifactIcon(
  artifactType: string,
): 'Image' | 'FileAudio' | 'FileVideo' | 'FileCode' | 'FileText' | 'File' {
  switch (artifactType) {
    case 'image':
    case 'svg':
      return 'Image'
    case 'audio':
      return 'FileAudio'
    case 'video':
      return 'FileVideo'
    case 'code':
    case 'html':
    case 'react':
      return 'FileCode'
    case 'file':
    default:
      return 'File'
  }
}
