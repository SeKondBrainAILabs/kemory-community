import { api } from './client'
import type { PIIScanResult, InjectionScanResult, FullScanResult } from './types'

/** Run the full security pipeline (PII + injection) on content. */
export async function fullScan(content: string): Promise<FullScanResult> {
  return api.post('api/v1/security/scan', { json: { content } }).json()
}

/** Scan content for personally identifiable information. */
export async function piiScan(content: string): Promise<PIIScanResult> {
  return api.post('api/v1/security/pii-scan', { json: { content } }).json()
}

/** Scan content for prompt injection and other attack patterns. */
export async function injectionScan(content: string): Promise<InjectionScanResult> {
  return api.post('api/v1/security/injection-scan', { json: { content } }).json()
}
