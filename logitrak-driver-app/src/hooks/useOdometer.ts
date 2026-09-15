import { useCallback, useEffect, useRef, useState } from 'react';
import { getVehicleOdometer, OdometerReading } from '@/api/ble';

/**
 * Odomètre matériel du véhicule ACTIF — donnée RÉELLE exposée par le backend.
 * - Aucun appel Navixy direct depuis l'app ; aucune estimation GPS.
 * - Si indisponible : `odometerKm` = null -> l'UI affiche « — » (jamais 0 fictif).
 * - Reset au changement de véhicule (pas de contamination A -> B).
 */
export function useOdometer(activeVehicleId?: string | null) {
  const [reading, setReading] = useState<OdometerReading | null>(null);
  const [loading, setLoading] = useState(false);
  const lastVehicle = useRef<string | null | undefined>(undefined);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setReading(await getVehicleOdometer());
    } catch {
      setReading(null); // pas de valeur inventée
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (lastVehicle.current !== undefined && lastVehicle.current !== activeVehicleId) {
      setReading(null);
    }
    lastVehicle.current = activeVehicleId ?? null;
    refresh();
  }, [activeVehicleId, refresh]);

  const available = reading?.status === 'OK' && typeof reading?.odometer_km === 'number';
  return {
    odometerKm: available ? (reading!.odometer_km as number) : null,
    available,
    status: reading?.status ?? null,
    loading,
    refresh,
  };
}
