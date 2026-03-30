/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './chat/templates/**/*.html',
  ],
  safelist: [
    // Classes adicionadas via classList.add() no JS — não aparecem no HTML estático
    'bg-emerald-50', 'bg-emerald-500',
    'bg-green-50', 'bg-green-500',
    'bg-red-50', 'bg-rose-50', 'bg-rose-500',
    'bg-blue-100',
    'border-emerald-500', 'border-green-200', 'border-green-500',
    'border-red-400', 'border-rose-500',
    'text-emerald-800', 'text-rose-800',
    'ring-1', 'ring-2', 'ring-green-100', 'ring-green-200',
    'animate-pulse',
    'opacity-0', 'opacity-80',
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ['Space Grotesk', 'sans-serif'],
        sans:    ['Inter', 'sans-serif'],
        serif:   ['Instrument Serif', 'serif'],
      },
      colors: {
        space: {
          950: '#010205',
          900: '#02040A',
          850: '#04060E',
          800: '#060913',
          700: '#0B1120',
        },
        brand: {
          primary:    '#ffffff',
          secondary:  '#9ca3af',
          accent:     '#22c55e',
          accentGlow: '#bbf7d0',
          warning:    '#f59e0b',
          neutral:    '#111111',
        },
      },
      animation: {
        'spin-slow':   'spin 15s linear infinite',
        'pulse-slow':  'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'float':       'float 6s ease-in-out infinite',
        'glow-pulse':  'glowPulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%':      { transform: 'translateY(-20px)' },
        },
        glowPulse: {
          '0%, 100%': { boxShadow: '0 0 15px rgba(34,197,94,0.2), inset 0 0 0 1px rgba(34,197,94,0.2)' },
          '50%':      { boxShadow: '0 0 35px rgba(34,197,94,0.5), inset 0 0 0 1px rgba(34,197,94,0.4)' },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
