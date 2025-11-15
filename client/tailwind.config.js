/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        kakao: {
          yellow: '#FEE500',
          brown: '#3C1E1E',
        },
        primary: {
          50: '#FFF9E6',
          100: '#FFF3CC',
          200: '#FFE799',
          300: '#FFDB66',
          400: '#FFCF33',
          500: '#FEE500',
          600: '#CBB700',
          700: '#988900',
          800: '#665C00',
          900: '#332E00',
        },
        gray: {
          50: '#F9FAFB',
          100: '#F3F4F6',
          200: '#E5E7EB',
          300: '#D1D5DB',
          400: '#9CA3AF',
          500: '#6B7280',
          600: '#4B5563',
          700: '#374151',
          800: '#1F2937',
          900: '#111827',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'kakao': '0 4px 6px -1px rgba(254, 229, 0, 0.3), 0 2px 4px -1px rgba(254, 229, 0, 0.2)',
      },
    },
  },
  plugins: [],
}
