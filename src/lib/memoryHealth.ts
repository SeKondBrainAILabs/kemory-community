/**
 * Memory Vault — Memory Health Utilities (KMV-E15)
 *
 * Pure functions for computing decay, time-to-archive, and display
 * labels from raw memory fields. All functions are deterministic and
 * unit-testable without a DOM or React context.
 */

export type ConsolidationStatus = 'pending' | 'consolidating' | 'archived'

export interface MemoryHealthInfo {
  /** Current weight, 0.01–1.0 */
  weight: number
  /** Days remaining before the memory is auto-archived (based on retention window) */
  daysUntilArchived: number | null
  /** Days remaining before weight hits the floor (0.01) at current decay rate */
  daysUntilFloor: number | null
  /** Human-readable label for the consolidation status */
  statusLabel: string
  /** Short plain-English phrase describing the memory's health */
  healthSentence: string
  /** Colour tier: 'fresh' | 'active' | 'fading' | 'archived' */
  tier: 'fresh' | 'active' | 'fading' | 'archived'
}

const DEFAULT_DECAY_RATE = 0.1   // 10% per day
const DEFAULT_RETENTION_DAYS = 10
const MIN_WEIGHT = 0.01

/**
 * Compute the number of days until the weight reaches MIN_WEIGHT
 * given the current weight and daily decay rate.
 *
 * Formula: n = log(MIN_WEIGHT / weight) / log(1 - rate)
 */
export function daysUntilWeightFloor(
  weight: number,
  decayRate: number = DEFAULT_DECAY_RATE,
): number {
  if (weight <= MIN_WEIGHT) return 0
  if (decayRate <= 0) return Infinity
  return Math.ceil(Math.log(MIN_WEIGHT / weight) / Math.log(1 - decayRate))
}

/**
 * Compute the number of days remaining before a memory is auto-archived,
 * based on when it was created and the namespace retention window.
 */
export function daysUntilArchived(
  createdAt: string | Date,
  retentionDays: number = DEFAULT_RETENTION_DAYS,
): number {
  const created = typeof createdAt === 'string' ? new Date(createdAt) : createdAt
  const now = new Date()
  const ageMs = now.getTime() - created.getTime()
  const ageDays = ageMs / (1000 * 60 * 60 * 24)
  return Math.max(0, Math.ceil(retentionDays - ageDays))
}

/**
 * Map a consolidation_status string to a human-readable label.
 */
export function statusLabel(status: ConsolidationStatus | string): string {
  switch (status) {
    case 'pending':       return 'Active'
    case 'consolidating': return 'Syncing to long-term'
    case 'archived':      return 'In long-term memory'
    default:              return status
  }
}

/**
 * Determine the visual health tier based on weight and status.
 * Tiers use a light, non-error palette:
 *   fresh   → weight ≥ 0.8 (indigo)
 *   active  → weight 0.4–0.79 (blue)
 *   fading  → weight < 0.4 (slate)
 *   archived → status === 'archived' (green)
 */
export function healthTier(
  weight: number,
  status: ConsolidationStatus | string,
): MemoryHealthInfo['tier'] {
  if (status === 'archived') return 'archived'
  if (weight >= 0.8) return 'fresh'
  if (weight >= 0.4) return 'active'
  return 'fading'
}

/**
 * Generate a plain-English health sentence for non-technical users.
 */
export function healthSentence(
  weight: number,
  status: ConsolidationStatus | string,
  daysLeft: number | null,
  daysToFloor: number | null,
): string {
  if (status === 'archived') {
    return 'This memory has been moved to long-term memory in Cognition OS.'
  }
  if (status === 'consolidating') {
    return 'This memory is currently being synced to long-term memory.'
  }
  const weightPct = Math.round(weight * 100)
  const archivePart = daysLeft !== null
    ? daysLeft === 0
      ? 'and will be archived today'
      : `and will be archived in ${daysLeft} day${daysLeft === 1 ? '' : 's'}`
    : ''
  const floorPart = daysToFloor !== null && daysToFloor > 0
    ? ` (weight reaches minimum in ~${daysToFloor} day${daysToFloor === 1 ? '' : 's'})`
    : ''
  return `Memory is at ${weightPct}% strength ${archivePart}${floorPart}.`
}

/**
 * Compute the full MemoryHealthInfo for a single memory.
 */
export function computeMemoryHealth(params: {
  weight?: number | null
  consolidationStatus?: string | null
  createdAt?: string | Date | null
  decayRate?: number
  retentionDays?: number
}): MemoryHealthInfo {
  const weight = params.weight ?? 1.0
  const status = (params.consolidationStatus ?? 'pending') as ConsolidationStatus
  const decayRate = params.decayRate ?? DEFAULT_DECAY_RATE
  const retentionDays = params.retentionDays ?? DEFAULT_RETENTION_DAYS

  const daysLeft = params.createdAt
    ? daysUntilArchived(params.createdAt, retentionDays)
    : null

  const daysToFloor = status !== 'archived'
    ? daysUntilWeightFloor(weight, decayRate)
    : null

  const tier = healthTier(weight, status)
  const sentence = healthSentence(weight, status, daysLeft, daysToFloor)
  const label = statusLabel(status)

  return {
    weight,
    daysUntilArchived: daysLeft,
    daysUntilFloor: daysToFloor,
    statusLabel: label,
    healthSentence: sentence,
    tier,
  }
}
