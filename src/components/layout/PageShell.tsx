import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

interface PageShellProps {
  children: ReactNode
}

export function PageShell({ children }: PageShellProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
    >
      {children}
    </motion.div>
  )
}
