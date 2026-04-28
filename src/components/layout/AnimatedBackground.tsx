/**
 * Pulse animated gradient background.
 *
 * Palette + treatment sourced from Core_Kora's globals.css (yellow #FDCB02,
 * magenta #F64DFE, blue #0598FA over white) and the Kanvas Figma
 * "02_OB_Home" frame, with a frosted white veil so foreground UI reads
 * cleanly over the drifting gradients.
 *
 * Animation is disabled automatically when the user has
 * prefers-reduced-motion: reduce.
 */
export function AnimatedBackground() {
  return (
    <>
      <div aria-hidden className="pulse-bg" />
      <div aria-hidden className="pulse-bg-veil" />
    </>
  )
}
