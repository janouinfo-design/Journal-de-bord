/**
 * Mode de sélection du véhicule côté chauffeur.
 * - 'manual' (défaut) : sélection manuelle du véhicule, UI épurée SANS widgets Bluetooth.
 * - 'ble' : ancien mode détection Bluetooth (conservé pour un usage futur/configurable).
 *
 * Configurable via EXPO_PUBLIC_VEHICLE_SELECTION_MODE. Le backend reste la source de vérité
 * de l'état (session, PRO/PRIVÉ, km). Ce flag ne pilote QUE l'affichage.
 */
export type VehicleSelectionMode = 'manual' | 'ble';

export const VEHICLE_SELECTION_MODE: VehicleSelectionMode =
  (process.env.EXPO_PUBLIC_VEHICLE_SELECTION_MODE as VehicleSelectionMode) === 'ble'
    ? 'ble'
    : 'manual';

export const isManualMode = () => VEHICLE_SELECTION_MODE === 'manual';
