import type { ReactNode } from 'react'

/**
 * S9N-6164: minimal, dependency-free markdown renderer for the Memory Detail
 * panel. Agents store structured content with headings, bold, lists and code;
 * the panel used to dump the raw source (`**Why:**`, `# heading`).
 *
 * SECURITY: this renderer NEVER uses dangerouslySetInnerHTML — every fragment
 * is emitted as a React element, so React escapes all text and there is no
 * HTML-injection surface. Link hrefs are additionally scheme-checked so a
 * `javascript:` URL in agent content can't produce a live link.
 */

const SAFE_LINK = /^(https?:\/\/|mailto:|\/)/i

// Inline: bold, italic, inline-code, link. Ordered so ** is tried before *.
const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  INLINE.lastIndex = 0
  let i = 0
  while ((m = INLINE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    const key = `${keyPrefix}-${i++}`
    if (tok.startsWith('**')) {
      out.push(<strong key={key}>{tok.slice(2, -2)}</strong>)
    } else if (tok.startsWith('`')) {
      out.push(
        <code key={key} className="rounded bg-surface-tertiary px-1 py-0.5 text-[0.85em]">
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (tok.startsWith('[')) {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(tok)
      const label = mm?.[1] ?? tok
      const href = mm?.[2] ?? ''
      if (mm && SAFE_LINK.test(href)) {
        out.push(
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-primaryDark underline"
          >
            {label}
          </a>,
        )
      } else {
        out.push(label)
      }
    } else {
      // single-asterisk italic
      out.push(<em key={key}>{tok.slice(1, -1)}</em>)
    }
    last = m.index + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const isUlLine = (s: string) => /^\s*[-*+]\s+/.test(s)
const isOlLine = (s: string) => /^\s*\d+\.\s+/.test(s)
const isHeading = (s: string) => /^#{1,6}\s+/.test(s)
const isFence = (s: string) => s.trimStart().startsWith('```')

export function MarkdownView({ content, className }: { content: string; className?: string }) {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const at = (n: number): string => lines[n] ?? ''
  const blocks: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = at(i)

    // Fenced code block
    if (isFence(line)) {
      const buf: string[] = []
      i++
      while (i < lines.length && !isFence(at(i))) {
        buf.push(at(i))
        i++
      }
      i++ // consume closing fence
      blocks.push(
        <pre
          key={key++}
          className="overflow-x-auto rounded-lg bg-surface-tertiary p-3 text-xs text-content-primary"
        >
          <code>{buf.join('\n')}</code>
        </pre>,
      )
      continue
    }

    // Heading
    const h = /^(#{1,6})\s+(.*)$/.exec(line)
    if (h) {
      const depth = (h[1] ?? '').length
      const size = depth <= 1 ? 'text-base' : depth === 2 ? 'text-sm' : 'text-xs'
      blocks.push(
        <p key={key++} className={`font-semibold text-content-primary ${size}`}>
          {renderInline(h[2] ?? '', `h${key}`)}
        </p>,
      )
      i++
      continue
    }

    // List (unordered or ordered) — group consecutive item lines
    if (isUlLine(line) || isOlLine(line)) {
      const ordered = isOlLine(line)
      const items: ReactNode[] = []
      while (i < lines.length && (isUlLine(at(i)) || isOlLine(at(i)))) {
        const text = at(i).replace(/^\s*(?:[-*+]|\d+\.)\s+/, '')
        items.push(<li key={items.length}>{renderInline(text, `li${key}-${items.length}`)}</li>)
        i++
      }
      blocks.push(
        ordered ? (
          <ol key={key++} className="list-decimal space-y-0.5 pl-5 text-content-primary">
            {items}
          </ol>
        ) : (
          <ul key={key++} className="list-disc space-y-0.5 pl-5 text-content-primary">
            {items}
          </ul>
        ),
      )
      continue
    }

    // Blank line
    if (line.trim() === '') {
      i++
      continue
    }

    // Paragraph — gather consecutive non-blank, non-special lines
    const para: string[] = []
    while (
      i < lines.length &&
      at(i).trim() !== '' &&
      !isFence(at(i)) &&
      !isHeading(at(i)) &&
      !isUlLine(at(i)) &&
      !isOlLine(at(i))
    ) {
      para.push(at(i))
      i++
    }
    blocks.push(
      <p key={key++} className="text-content-primary">
        {renderInline(para.join(' '), `p${key}`)}
      </p>,
    )
  }

  return <div className={`space-y-2 text-sm leading-relaxed ${className ?? ''}`}>{blocks}</div>
}
