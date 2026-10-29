/**
 * Lecture humaine des erreurs API (Lot 5) — sans jargon, sans secret.
 * Le backend renvoie soit `detail: string` (refus legacy), soit `detail: {code, msg, ...}`
 * (module coupé, permission manquante, compte désactivé, client suspendu).
 */
export type ApiErrorDetail = string | { code?: string; msg?: string; module?: string; permission?: string } | null;

export const ACCESS_MESSAGES: Record<string, string> = {
  module_disabled: "Cette fonction n'est pas activée pour votre entreprise.",
  permission_denied: "Vous n'avez pas l'autorisation pour cette action. Contactez votre administrateur.",
  account_disabled: 'Votre compte a été désactivé. Contactez votre administrateur.',
  tenant_suspended: 'Accès entreprise suspendu — contactez Logitrak.',
  tenant_missing: "Aucune entreprise n'est associée à votre compte.",
  invalid_tenant: 'Entreprise inconnue.',
};

export function errorCode(e: unknown): string | null {
  const d = (e as { response?: { data?: { detail?: ApiErrorDetail } } })?.response?.data?.detail;
  return d && typeof d === 'object' && d.code ? d.code : null;
}

export function describeApiError(e: unknown, fallback: string): string {
  const resp = (e as { response?: { status?: number; data?: { detail?: ApiErrorDetail } } })?.response;
  const d = resp?.data?.detail;
  if (d && typeof d === 'object') {
    if (d.code && ACCESS_MESSAGES[d.code]) return ACCESS_MESSAGES[d.code];
    if (d.msg) return d.msg;
  }
  if (typeof d === 'string' && d.trim()) return d;
  return fallback;
}

export function isAccessDenied(e: unknown): boolean {
  const code = errorCode(e);
  return code === 'module_disabled' || code === 'permission_denied';
}
