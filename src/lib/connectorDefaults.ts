/**
 * Defaults for the connector wizards (Claude Desktop, Claude Code, generic MCP).
 *
 * The browser can't tell us where the user's Kemory repo lives, so we pick
 * sensible defaults by looking at how the dashboard itself was reached:
 *
 * - `localhost` or a LAN IP → local dev, Kemory API on :8100
 * - `app.<rest>` FQDN → mirror the `app.`/`api.` split used by the gateway
 * - anything else → same origin as the dashboard (user will likely edit)
 *
 * The script-path default is best-effort: `/opt/kemory` for packaged installs,
 * this repo's absolute path when the dashboard is served from a *.dxb-gw host
 * (which on this machine is always /etc/hosts → 127.0.0.1) or localhost.
 */

const LOCAL_REPO_PATH =
  '/Volumes/DataDrive/Repos/sekond/agent_memory_vault/agent_memory_vault'
const DEPLOYED_REPO_PATH = '/opt/kemory'
const SCRIPT_RELATIVE = 'scripts/kemory_mcp_server.py'

function isLanHost(host: string): boolean {
  return (
    host === 'localhost' ||
    host === '127.0.0.1' ||
    host.startsWith('10.') ||
    host.startsWith('192.168.') ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(host)
  )
}

function isDevGatewayHost(host: string): boolean {
  // Caddy gateway hostnames that /etc/hosts points at 127.0.0.1 on the dev box.
  return host.endsWith('.dxb-gw.basanti.ai') || host.endsWith('.kora.test')
}

export function defaultApiUrl(): string {
  if (typeof window === 'undefined') return 'http://localhost:8100'
  const { hostname, origin } = window.location
  if (isLanHost(hostname)) return `http://${hostname}:8100`
  if (hostname.startsWith('app.')) {
    return `https://api.${hostname.slice('app.'.length)}`
  }
  return origin
}

export function defaultScriptPath(): string {
  if (typeof window === 'undefined') return `${DEPLOYED_REPO_PATH}/${SCRIPT_RELATIVE}`
  const { hostname } = window.location
  const base = isLanHost(hostname) || isDevGatewayHost(hostname)
    ? LOCAL_REPO_PATH
    : DEPLOYED_REPO_PATH
  return `${base}/${SCRIPT_RELATIVE}`
}
