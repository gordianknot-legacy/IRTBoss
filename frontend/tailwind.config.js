/**
 * Design tokens live in `src/styles/tokens.css` as CSS custom properties, and
 * this file only *names* them for Tailwind. The indirection is what makes the
 * dark theme a single block of variable overrides instead of a `dark:` variant
 * on every element — and it means no component can invent a colour that is not
 * in the system, because there are no raw hex values to reach for.
 */

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // Replaced, not extended: the default Tailwind palette is exactly the
    // escape hatch this design system exists to close.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',

      canvas: 'rgb(var(--c-canvas) / <alpha-value>)',
      surface: 'rgb(var(--c-surface) / <alpha-value>)',
      raised: 'rgb(var(--c-raised) / <alpha-value>)',
      sunken: 'rgb(var(--c-sunken) / <alpha-value>)',

      ink: 'rgb(var(--c-ink) / <alpha-value>)',
      'ink-muted': 'rgb(var(--c-ink-muted) / <alpha-value>)',
      'ink-faint': 'rgb(var(--c-ink-faint) / <alpha-value>)',
      'ink-inverse': 'rgb(var(--c-ink-inverse) / <alpha-value>)',

      rule: 'rgb(var(--c-rule) / <alpha-value>)',
      'rule-strong': 'rgb(var(--c-rule-strong) / <alpha-value>)',

      accent: 'rgb(var(--c-accent) / <alpha-value>)',
      'accent-soft': 'rgb(var(--c-accent-soft) / <alpha-value>)',

      // Semantic, and deliberately not named "good"/"bad". Nothing in this
      // product passes or fails; `attention` means "read this", `absent` means
      // "there is no number here".
      attention: 'rgb(var(--c-attention) / <alpha-value>)',
      'attention-soft': 'rgb(var(--c-attention-soft) / <alpha-value>)',
      absent: 'rgb(var(--c-absent) / <alpha-value>)',
      'absent-soft': 'rgb(var(--c-absent-soft) / <alpha-value>)',
      alarm: 'rgb(var(--c-alarm) / <alpha-value>)',
      'alarm-soft': 'rgb(var(--c-alarm-soft) / <alpha-value>)',
      steady: 'rgb(var(--c-steady) / <alpha-value>)',
      'steady-soft': 'rgb(var(--c-steady-soft) / <alpha-value>)',

      // Chart series, fixed order, never cycled.
      'series-1': 'rgb(var(--c-series-1) / <alpha-value>)',
      'series-2': 'rgb(var(--c-series-2) / <alpha-value>)',
    },
    fontFamily: {
      sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
      display: ['Iowan Old Style', 'Palatino Linotype', 'Georgia', 'serif'],
      mono: ['ui-monospace', 'SFMono-Regular', 'Cascadia Mono', 'Consolas', 'monospace'],
    },
    fontSize: {
      // A 6-step scale. Anything not on it is a mistake, not a nuance.
      micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.06em' }],
      small: ['0.8125rem', { lineHeight: '1.25rem' }],
      body: ['0.9375rem', { lineHeight: '1.55rem' }],
      lede: ['1.0625rem', { lineHeight: '1.7rem' }],
      title: ['1.375rem', { lineHeight: '1.9rem', letterSpacing: '-0.01em' }],
      display: ['2rem', { lineHeight: '2.4rem', letterSpacing: '-0.02em' }],
    },
    spacing: {
      // 4px base, named by step so the vocabulary stays small.
      0: '0px',
      px: '1px',
      1: '0.25rem',
      2: '0.5rem',
      3: '0.75rem',
      4: '1rem',
      5: '1.5rem',
      6: '2rem',
      7: '3rem',
      8: '4rem',
      9: '6rem',
    },
    borderRadius: {
      none: '0',
      sm: '2px',
      DEFAULT: '4px',
      lg: '8px',
      full: '9999px',
    },
    extend: {
      maxWidth: {
        prose: '68ch',
        page: '82rem',
      },
      boxShadow: {
        card: '0 1px 2px rgb(var(--c-shadow) / 0.06), 0 8px 24px -12px rgb(var(--c-shadow) / 0.18)',
      },
    },
  },
  plugins: [],
}
