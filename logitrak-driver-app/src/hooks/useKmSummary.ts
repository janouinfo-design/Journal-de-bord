import { useCallback, useEffect, useRef, useState } from 'react';
import { getKmSummary, KmSummary, KmPeriod } from '@/api/ble';

/**
 * Km Pro / Km Privé du véhicule ACTIF (source backend uniquement).
 * - Aucun calcul GPS mobile : on n'affiche que ce que le backend renvoie.
 * - Reset à chaque changement de véhicule (pas de contamination A -> B).
 * - Valeurs null -> l'UI affiche « — » (jamais une fausse valeur).
 * - `period` est réactif : changer Aujourd'hui/Semaine/Mois refetch les vraies valeurs.
 *
 * `activeVehicleId` permet d'invalider proprement au changement de véhicule.
 */
export function useKmSummary(activeVehicleId?: string | null, period: KmPeriod = 'today') {
  const [summary, setSummary] = useState<KmSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const lastVehicle = useRef<string | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const s = await getKmSummary(period);
      setSummary(s);
    } catch {
      // erreur -> pas de valeur inventée
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [period]);

  // Reset immédiat quand le véhicule actif change (pas de contamination inter-véhicule),
  // puis refetch. Le refetch se déclenche aussi quand `period` change (via refresh dep).
  useEffect(() => {
    if (lastVehicle.current !== undefined && lastVehicle.current !== activeVehicleId) {
      setSummary(null);
    }
    lastVehicle.current = activeVehicleId ?? null;
    refresh();
  }, [activeVehicleId, refresh]);

  return {
    period,
    periodLabel: summary?.period_label ?? null,
    proKm: summary?.available ? summary.pro_km : null,
    privateKm: summary?.available ? summary.private_km : null,
    available: !!summary?.available,
    loading,
    refresh,
  };
}
