import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: '#6366f1',
          secondary: '#8b5cf6',
        },
        // Pulse / Kora signature palette (from Core_Kora + Figma Kanvas design)
        pulse: {
          blue: '#0598fa',
          magenta: '#f64dfe',
          yellow: '#fdcb02',
        },
        accent: {
          blue: '#3b82f6',
        },
        surface: {
          primary: '#ffffff',
          secondary: '#f8f9fa',
          tertiary: '#f1f3f5',
        },
        content: {
          primary: '#1a1a1a',
          secondary: '#6b7280',
          tertiary: '#9ca3af',
        },
        border: {
          DEFAULT: '#e5e7eb',
        },
        status: {
          success: '#16a34a',
          warning: '#d97706',
          danger: '#dc2626',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
      },
      borderRadius: {
        sm: '6px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,0.05)',
        md: '0 4px 6px rgba(0,0,0,0.1)',
        lg: '0 10px 15px rgba(0,0,0,0.1)',
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'gradient-drift': 'gradient-drift 24s ease-in-out infinite',
        'gradient-slow': 'gradient-drift 40s ease-in-out infinite',
      },
      keyframes: {
        'gradient-drift': {
          '0%, 100%': {
            transform: 'translate3d(0,0,0) scale(1)',
            opacity: '0.9',
          },
          '25%': {
            transform: 'translate3d(2%,-1%,0) scale(1.05)',
            opacity: '1',
          },
          '50%': {
            transform: 'translate3d(-1%,2%,0) scale(1.08)',
            opacity: '0.95',
          },
          '75%': {
            transform: 'translate3d(-2%,-1%,0) scale(1.03)',
            opacity: '1',
          },
        },
      },
      backdropBlur: {
        pulse: '25px',
        glass: '40px',
      },
      width: {
        'pulse-rail': '60px',
      },
    },
  },
  plugins: [],
} satisfies Config
