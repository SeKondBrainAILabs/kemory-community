export type PlatformStyle = { label: string; short: string; className: string }

export const OTHER_STYLE: PlatformStyle = {
  label: 'Other',
  short: '?',
  className: 'bg-gray-100 text-gray-600 ring-gray-200',
}

export const PLATFORM_STYLE: Record<string, PlatformStyle> = {
  claude: { label: 'Claude', short: 'C', className: 'bg-orange-100 text-orange-700 ring-orange-200' },
  chatgpt: { label: 'ChatGPT', short: 'G', className: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
  gemini: { label: 'Gemini', short: 'M', className: 'bg-blue-100 text-blue-700 ring-blue-200' },
  manus: { label: 'Manus', short: 'N', className: 'bg-violet-100 text-violet-700 ring-violet-200' },
  cursor: { label: 'Cursor', short: 'U', className: 'bg-gray-200 text-gray-700 ring-gray-300' },
  other: OTHER_STYLE,
}

export function platformStyle(platform: string | null | undefined): PlatformStyle {
  return (platform && PLATFORM_STYLE[platform]) || OTHER_STYLE
}

export function PlatformBadge({ platform }: { platform: string | null | undefined }) {
  const style = platformStyle(platform)
  return (
    <span
      className={`inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[10px] font-semibold ring-1 ${style.className}`}
      title={style.label}
      aria-label={style.label}
    >
      {style.short}
    </span>
  )
}
