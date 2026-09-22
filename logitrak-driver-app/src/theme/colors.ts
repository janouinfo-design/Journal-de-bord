/**
 * Logitrak Driver — palette LIGHT premium.
 * Fond gris très clair + cartes blanches, accent bleu LOGITRAK.
 * Tous les écrans consomment ces tokens : changer ici change toute l'app.
 *
 * Tokens "soft" : fonds pâles des badges/bannières (remplacent les rgba(...) en dur
 * qui étaient conçus pour le dark). Garantit un contraste correct en thème clair.
 */
export const colors = {
  // Base
  bg: '#f1f5f9',          // fond application (slate-100)
  bgElevated: '#ffffff',
  bgCard: '#ffffff',      // cartes
  border: '#e2e8f0',      // bordures (slate-200)

  // Text
  text: '#0f172a',        // texte principal (slate-900)
  textMuted: '#64748b',   // texte secondaire (slate-500)
  textInverse: '#ffffff', // texte sur fond coloré (boutons pleins)

  // Accents
  primary: '#2563eb',     // bleu LOGITRAK (action / actif)
  primaryDark: '#1d4ed8',
  primarySoft: '#eff4ff', // fond bleu très clair (état actif / badges)
  perso: '#475569',       // gris ardoise (mode privé)
  persoSoft: '#f1f5f9',
  pro: '#2563eb',
  proSoft: '#eff4ff',

  // Status
  success: '#16a34a',
  successSoft: '#dcfce7',
  warning: '#b45309',     // texte d'alerte lisible sur fond clair
  warningSoft: '#fffbeb',
  warningBorder: '#fcd34d',
  danger: '#dc2626',
  dangerSoft: '#fef2f2',
  pulseGreen: '#16a34a',

  // Overlays
  overlay: 'rgba(15,23,42,0.45)',   // fond de modale (slate-900 translucide)
  hairline: 'rgba(15,23,42,0.06)',  // ombre/hairline légère
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
