import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './hooks/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Bloomberg Terminal Color Palette
        'bg-primary': '#0a0a0a',
        'bg-secondary': '#1a1a1a',
        'bg-tertiary': '#2a2a2a',

        'text-primary': '#f0f0f0',
        'text-secondary': '#a0a0a0',

        'accent-orange': '#ff8c00',
        'accent-amber': '#ffb700',

        'terminal-green': '#00ff00',
        'terminal-red': '#ff0000',

        'border-color': '#333333',

        // Extend default grays for terminal aesthetic
        gray: {
          800: '#2a2a2a',
          850: '#1a1a1a',
          900: '#0f0f0f',
          950: '#0a0a0a',
        },

        // Bloomberg orange variants
        orange: {
          400: '#ffb700',
          500: '#ff8c00',
          600: '#e07b00',
        },

        // Terminal green variants
        green: {
          400: '#00ff00',
          500: '#00dd00',
          600: '#00bb00',
        },

        // Terminal red variants
        red: {
          400: '#ff0000',
          500: '#dd0000',
          600: '#bb0000',
        },
      },
      fontFamily: {
        mono: ['Courier New', 'Courier', 'monospace'],
      },
      animation: {
        'scroll-left': 'scroll-left 60s linear infinite',
        'pulse': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        'scroll-left': {
          from: { transform: 'translateX(0)' },
          to: { transform: 'translateX(-50%)' },
        },
        pulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '.5' },
        },
      },
    },
  },
  plugins: [],
}

export default config
