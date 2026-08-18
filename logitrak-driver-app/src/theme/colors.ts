/**
 * Logitrak Driver — color palette
 * Mirrors the dark, accent-blue aesthetic of the web /driver console.
 */
export const colors = {
  // Base
  bg: '#0f172a',
  bgElevated: '#1e293b',
  bgCard: '#1e293b',
  border: '#334155',

  // Text
  text: '#f8fafc',
  textMuted: '#94a3b8',
  textInverse: '#0f172a',

  // Accents
  primary: '#3b82f6',
  primaryDark: '#2563eb',
  perso: '#475569',
  pro: '#3b82f6',

  // Status
  success: '#22c55e',
  warning: '#facc15',
  danger: '#ef4444',
  pulseGreen: '#22c55e',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radius = {
  sm: 6,
  md: 12,
  lg: 18,
  pill: 999,
} as const;

export const font = {
  size: {
    xs: 11,
    sm: 13,
    md: 15,
    lg: 17,
    xl: 22,
    xxl: 28,
    hero: 36,
  },
  weight: {
    regular: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  },
} as const;
