import { Trip, TripClassification } from '@/api/trips';
import { colors } from '@/theme/colors';

/** Formate une date ISO en date courte FR, ou N/A. */
export function formatDate(iso?: string | null): string {
  if (!iso) return 'N/A';
  try {
    return new Date(iso).toLocaleDateString('fr-CH', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return 'N/A';
  }
}

/** Formate une date ISO en heure FR (HH:mm), ou N/A. */
export function formatTime(iso?: string | null): string {
  if (!iso) return 'N/A';
  try {
    return new Date(iso).toLocaleTimeString('fr-CH', {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return 'N/A';
  }
}

/** Durée lisible depuis des minutes réelles. N/A si absent. */
export function formatDuration(min?: number | null): string {
  if (min == null || Number.isNaN(min)) return 'N/A';
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  if (h > 0) return `${h} h ${m.toString().padStart(2, '0')}`;
  return `${m} min`;
}

/** Distance réelle en km, ou N/A. */
export function formatDistance(km?: number | null): string {
  if (km == null || Number.isNaN(km)) return 'N/A';
  return `${km.toFixed(1)} km`;
}

export type ClassificationBadge = {
  label: string;
  color: string;
  bg: string;
};

/** Badge PRO / PRIVÉ / À classer selon la classification RÉELLE (null = à classer). */
export function classificationBadge(c: TripClassification): ClassificationBadge {
  if (c === 'professional') {
    return { label: 'PRO', color: colors.primary, bg: 'rgba(59,130,246,0.15)' };
  }
  if (c === 'personal') {
    return { label: 'PRIVÉ', color: colors.perso, bg: 'rgba(71,85,105,0.20)' };
  }
  return { label: 'À classer', color: colors.warning, bg: 'rgba(245,158,11,0.15)' };
}

/** Titre court d'un trajet : "Origine → Destination" (adresses réelles). */
export function tripRouteLabel(t: Trip): { from: string; to: string } {
  return {
    from: t.start_address || 'Origine inconnue',
    to: t.end_address || 'Destination inconnue',
  };
}
