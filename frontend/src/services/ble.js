import { Platform, PermissionsAndroid } from 'react-native';

/**
 * Service de scan BLE.
 *
 * IMPORTANT (règle "données réelles uniquement") :
 * - react-native-ble-plx ne fonctionne QUE dans un build natif (development build EAS),
 *   PAS dans Expo Go ni sur le web.
 * - Sur web ou si le module natif est absent, ce service reste dans l'état "unavailable"
 *   et NE FABRIQUE AUCUNE détection. L'UI doit afficher un état clair.
 *
 * L'état exposé (isSupported) permet à l'UI de décider quoi afficher.
 */

let BleManager = null;
let bleModuleError = null;

// Chargement paresseux : évite le crash de bundling web.
if (Platform.OS !== 'web') {
  try {
    // eslint-disable-next-line global-require
    const ble = require('react-native-ble-plx');
    BleManager = ble.BleManager;
  } catch (e) {
    bleModuleError = e;
  }
}

class BleService {
  constructor() {
    this.manager = null;
    this.scanning = false;
    this.listeners = new Set();
  }

  /** Le scan BLE natif est-il disponible sur cette plateforme ? */
  isSupported() {
    return Platform.OS !== 'web' && !!BleManager && !bleModuleError;
  }

  /** Raison lisible de l'indisponibilité (pour l'UI). */
  unavailableReason() {
    if (Platform.OS === 'web') {
      return "Le scan Bluetooth n'est pas disponible dans le navigateur. Utilisez l'application mobile (build natif) pour la détection automatique.";
    }
    if (bleModuleError || !BleManager) {
      return "Module Bluetooth natif indisponible. Un development build EAS est requis (le scan ne fonctionne pas dans Expo Go).";
    }
    return null;
  }

  _getManager() {
    if (!this.isSupported()) return null;
    if (!this.manager) this.manager = new BleManager();
    return this.manager;
  }

  subscribe(cb) {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  _emit(evt) {
    this.listeners.forEach((cb) => {
      try { cb(evt); } catch (e) {}
    });
  }

  async requestPermissions() {
    if (Platform.OS !== 'android') return true;
    try {
      const perms = [
        PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
      ].filter(Boolean);
      const granted = await PermissionsAndroid.requestMultiple(perms);
      return Object.values(granted).every(
        (v) => v === PermissionsAndroid.RESULTS.GRANTED
      );
    } catch (e) {
      return false;
    }
  }

  /**
   * Démarre le scan BLE réel.
   * @param {Function} onDevice reçoit { id, name, rssi, timestamp }
   * @param {Object} opts { serviceUUIDs }
   */
  async startScan(onDevice, opts = {}) {
    if (!this.isSupported()) {
      this._emit({ type: 'error', reason: this.unavailableReason() });
      return false;
    }
    const manager = this._getManager();
    if (!manager) return false;

    const ok = await this.requestPermissions();
    if (!ok) {
      this._emit({ type: 'error', reason: "Autorisations Bluetooth refusées." });
      return false;
    }

    // Attendre que l'adaptateur soit allumé.
    const state = await manager.state();
    if (state !== 'PoweredOn') {
      this._emit({ type: 'state', state });
    }

    this.scanning = true;
    this._emit({ type: 'scanning', scanning: true });

    manager.startDeviceScan(
      opts.serviceUUIDs || null,
      { allowDuplicates: true },
      (error, device) => {
        if (error) {
          this.scanning = false;
          this._emit({ type: 'error', reason: error?.message || 'Erreur de scan BLE.' });
          return;
        }
        if (device) {
          const evt = {
            type: 'device',
            device: {
              id: device.id,
              name: device.name || device.localName || null,
              rssi: device.rssi,
              timestamp: Date.now(),
            },
          };
          this._emit(evt);
          if (onDevice) onDevice(evt.device);
        }
      }
    );
    return true;
  }

  stopScan() {
    if (this.manager && this.scanning) {
      try { this.manager.stopDeviceScan(); } catch (e) {}
    }
    this.scanning = false;
    this._emit({ type: 'scanning', scanning: false });
  }

  destroy() {
    this.stopScan();
    if (this.manager) {
      try { this.manager.destroy(); } catch (e) {}
      this.manager = null;
    }
  }
}

export const bleService = new BleService();
