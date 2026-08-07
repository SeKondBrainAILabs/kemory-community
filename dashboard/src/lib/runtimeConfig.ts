export interface RuntimeConfig {
  API_KEY?: string
  API_URL?: string
}

let config: RuntimeConfig | null = null

export async function loadConfig(): Promise<RuntimeConfig> {
  if (config) return config
  try {
    const response = await fetch('/config.json')
    if (response.ok) config = await response.json()
  } catch {
    // Build-time values below keep local development usable without nginx.
  }
  config ??= {
    API_KEY: import.meta.env.VITE_KEMORY_API_KEY,
    API_URL: import.meta.env.VITE_API_URL,
  }
  return config
}

export function getConfig(): RuntimeConfig | null {
  return config
}
