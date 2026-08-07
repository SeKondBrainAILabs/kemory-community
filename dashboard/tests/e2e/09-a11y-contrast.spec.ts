import { test, expect, type Page } from '@playwright/test'

/**
 * S9N-6165: automated WCAG-AA contrast smoke.
 *
 * Ports the UX-audit sweep into CI: for every leaf text node in <main>, compute
 * the contrast ratio of its computed color against its effective background and
 * assert it clears the WCAG AA threshold (4.5:1 normal, 3:1 large/bold). This is
 * the acceptance gate for the a11y tickets across every page epic — run it per
 * route as each epic lands and keep the failure list at zero.
 *
 * Relative paths only, so CI can point baseURL at the local stack, staging, or
 * prod. Pages behind data that may be empty still exercise page chrome.
 */

type Failure = { text: string; ratio: number; size: number; color: string }

async function contrastFailures(page: Page): Promise<Failure[]> {
  return page.evaluate(() => {
    function lum(r: number, g: number, b: number) {
      const f = (c: number) => {
        c /= 255
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
      }
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    }
    function parse(c: string): [number, number, number] | null {
      const m = c.match(/\d+(\.\d+)?/g)
      return m ? (m.slice(0, 3).map(Number) as [number, number, number]) : null
    }
    function bg(el: Element): [number, number, number] {
      let e: Element | null = el
      while (e) {
        const c = getComputedStyle(e).backgroundColor
        const p = parse(c)
        if (p && !(c.includes('rgba') && c.endsWith(', 0)'))) return p
        e = e.parentElement
      }
      return [255, 255, 255]
    }
    const out: Failure[] = []
    const seen = new Set<string>()
    for (const el of Array.from(document.querySelectorAll('main *'))) {
      if (el.children.length > 0) continue
      const t = el.textContent?.trim()
      if (!t || t.length < 2 || t.length > 70) continue
      const st = getComputedStyle(el)
      if (st.visibility === 'hidden' || st.display === 'none') continue
      const fg = parse(st.color)
      if (!fg) continue
      const bgc = bg(el)
      const L1 = lum(...fg)
      const L2 = lum(...bgc)
      const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)
      const size = parseFloat(st.fontSize)
      const bold = parseInt(st.fontWeight) >= 700
      const req = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5
      if (ratio < req) {
        const key = t.slice(0, 24) + ratio.toFixed(1)
        if (seen.has(key)) continue
        seen.add(key)
        out.push({ text: t.slice(0, 40), ratio: +ratio.toFixed(2), size, color: st.color })
      }
    }
    return out
  })
}

// Pages onboarded to the contrast gate as each epic lands. Add routes here
// (memories done — S9N-6165) until all 15 are covered.
const GATED_ROUTES = ['/memories']

for (const route of GATED_ROUTES) {
  test(`WCAG AA contrast — ${route}`, async ({ page }) => {
    await page.goto(route, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(3000)
    const failures = await contrastFailures(page)
    expect(
      failures,
      `AA contrast failures on ${route}:\n${failures.map((f) => `  ${f.ratio}:1 ${f.size}px "${f.text}" (${f.color})`).join('\n')}`,
    ).toEqual([])
  })
}
