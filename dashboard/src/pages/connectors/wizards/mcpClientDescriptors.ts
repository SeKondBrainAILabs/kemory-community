import type { McpClientDescriptor } from './McpClientWizard'
import {
  PROMPT_GENERIC_MCP,
  PROMPT_CLINE,
  PROMPT_CHATGPT_REST,
} from '@/lib/connectorSystemPrompts'

/**
 * Catalogue of MCP clients onboarded via the generic McpClientWizard.
 * Keyed by ConnectorId (see ConnectorsPage).
 */
export const mcpClientDescriptors: Record<string, McpClientDescriptor> = {
  cursor: {
    id: 'cursor',
    name: 'Cursor',
    agentName: 'cursor-agent',
    agentDescription: 'Cursor IDE — persistent memory MCP agent',
    configPaths: [
      { os: 'macOS', path: '~/.cursor/mcp.json', label: 'mcp.json' },
      { os: 'Linux', path: '~/.cursor/mcp.json', label: 'mcp.json' },
      { os: 'Windows', path: '%USERPROFILE%\\.cursor\\mcp.json', label: 'mcp.json' },
    ],
    projectScopedHint:
      'You can also commit a project-local `.cursor/mcp.json` at the repo root for team-wide sharing.',
    notes: [
      'Settings → MCP → toggle the "kemory" server on after saving.',
      'Cursor shows tool invocations inline in the chat panel.',
    ],
    systemPromptTemplate: PROMPT_GENERIC_MCP,
    promptDestination: 'Cursor Rules (.cursorrules) or project .cursor/rules',
  },
  windsurf: {
    id: 'windsurf',
    name: 'Windsurf',
    agentName: 'windsurf-agent',
    agentDescription: 'Codeium Windsurf — persistent memory MCP agent',
    configPaths: [
      { os: 'macOS', path: '~/.codeium/windsurf/mcp_config.json', label: 'mcp_config.json' },
      { os: 'Linux', path: '~/.codeium/windsurf/mcp_config.json', label: 'mcp_config.json' },
      { os: 'Windows', path: '%USERPROFILE%\\.codeium\\windsurf\\mcp_config.json', label: 'mcp_config.json' },
    ],
    notes: [
      'Cascade → Settings → Plugins → Refresh, then enable "kemory".',
    ],
    systemPromptTemplate: PROMPT_GENERIC_MCP,
    promptDestination: 'Windsurf Global Rules or .windsurfrules',
  },
  cline: {
    id: 'cline',
    name: 'Cline',
    agentName: 'cline-agent',
    agentDescription: 'Cline (VS Code) — persistent memory MCP agent',
    configPaths: [
      { os: 'macOS', path: '~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json', label: 'cline_mcp_settings.json' },
      { os: 'Linux', path: '~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json', label: 'cline_mcp_settings.json' },
      { os: 'Windows', path: '%APPDATA%\\Code\\User\\globalStorage\\saoudrizwan.claude-dev\\settings\\cline_mcp_settings.json', label: 'cline_mcp_settings.json' },
    ],
    notes: [
      'Open the Cline sidebar → MCP Servers → Edit. Saving reloads servers automatically.',
    ],
    systemPromptTemplate: PROMPT_CLINE,
    promptDestination: 'Cline Custom Instructions (sidebar → ⚙ → Custom Instructions)',
  },
  codex: {
    id: 'codex',
    name: 'ChatGPT / Codex CLI',
    agentName: 'codex-agent',
    agentDescription: 'OpenAI Codex CLI — persistent memory MCP agent',
    configPaths: [
      { os: 'macOS', path: '~/.codex/config.toml', label: 'config.toml' },
      { os: 'Linux', path: '~/.codex/config.toml', label: 'config.toml' },
      { os: 'Windows', path: '%USERPROFILE%\\.codex\\config.toml', label: 'config.toml' },
    ],
    notes: [
      'Codex uses TOML — wrap the JSON below under an `[mcp_servers.kemory]` table with `command`, `args`, and `env` keys.',
      'Example TOML form is shown after registration; the JSON version is also valid if you keep it under a "json" key.',
    ],
    systemPromptTemplate: PROMPT_CHATGPT_REST,
    promptDestination: 'ChatGPT Custom Instructions or Codex CLI --instructions flag',
  },
  'gemini-cli': {
    id: 'gemini-cli',
    name: 'Gemini CLI',
    agentName: 'gemini-cli-agent',
    agentDescription: 'Google Gemini CLI — persistent memory MCP agent',
    configPaths: [
      { os: 'macOS', path: '~/.gemini/settings.json', label: 'settings.json' },
      { os: 'Linux', path: '~/.gemini/settings.json', label: 'settings.json' },
      { os: 'Windows', path: '%USERPROFILE%\\.gemini\\settings.json', label: 'settings.json' },
    ],
    notes: [
      'Gemini CLI reloads settings on next invocation — no explicit restart needed.',
    ],
    systemPromptTemplate: PROMPT_GENERIC_MCP,
    promptDestination: 'Gemini CLI --system_prompt flag or GEMINI.md',
  },
  ollama: {
    id: 'ollama',
    name: 'Ollama',
    agentName: 'ollama-agent',
    agentDescription: 'Ollama (local LLM) — persistent memory MCP agent',
    configPaths: [
      { os: 'macOS', path: '~/.ollama/mcp.json', label: 'mcp.json' },
      { os: 'Linux', path: '~/.ollama/mcp.json', label: 'mcp.json' },
      { os: 'Windows', path: '%USERPROFILE%\\.ollama\\mcp.json', label: 'mcp.json' },
    ],
    notes: [
      'Native Ollama MCP support is in beta — pair with an MCP-aware client (Open WebUI, Msty) if your Ollama build does not expose mcp.json directly.',
    ],
    systemPromptTemplate: PROMPT_GENERIC_MCP,
    promptDestination: 'your Ollama modelfile SYSTEM block or host client system prompt',
  },
  'custom-mcp': {
    id: 'custom-mcp',
    name: 'Custom MCP Client',
    agentName: 'custom-mcp-agent',
    agentDescription: 'User-built MCP client — persistent memory MCP agent',
    configPaths: [
      { os: 'macOS', path: 'Wherever your client reads MCP server config', label: 'mcp.json' },
      { os: 'Linux', path: 'Wherever your client reads MCP server config', label: 'mcp.json' },
      { os: 'Windows', path: 'Wherever your client reads MCP server config', label: 'mcp.json' },
    ],
    projectScopedHint:
      'Use the JSON below as a starting point — every MCP-compliant client accepts this shape.',
    notes: [
      'The bridge speaks MCP over stdio. If your client only speaks SSE/HTTP, run it as a long-lived process and forward via your client\'s HTTP transport.',
    ],
    systemPromptTemplate: PROMPT_GENERIC_MCP,
    promptDestination: 'your agent\'s system message',
  },
}
