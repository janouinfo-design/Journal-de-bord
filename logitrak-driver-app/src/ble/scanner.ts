import { BleManager, Device, State, Subscription } from 'react-native-ble-plx';
import { logger } from '@/utils/logger';
import { enqueue } from './queue';
import { requestBlePermissions } from '@/utils/permissions';

export type ScannerState =
  | 'idle'
  | 'requesting-permissions'
  | 'starting'
  | 'scanning'
  | 'paused'
  | 'error';

export type ScannerCallbacks = {
  onStateChange?: (s: ScannerState) => void;
  onDetection?: (identifier: string, rssi: number) => void;
  onError?: (msg: string) => void;
};

class BleScanner {
  private manager: BleManager | null = null;
  private stateSubscription: Subscription | null = null;
  private callbacks: ScannerCallbacks = {};
  private currentState: ScannerState = 'idle';
  private deviceFilter: string[] | null = null; // optional whitelist of identifiers
  private dedupeMap: Map<string, number> = new Map();
  private readonly DEDUPE_WINDOW_MS = 2_000;

  setCallbacks(cb: ScannerCallbacks) {
    this.callbacks = cb;
  }

  setDeviceFilter(ids: string[] | null) {
    this.deviceFilter = ids;
  }

  getState(): ScannerState {
    return this.currentState;
  }

  private setState(next: ScannerState) {
    this.currentState = next;
    this.callbacks.onStateChange?.(next);
  }

  /** Start scanning. Idempotent. */
  async start(): Promise<boolean> {
    if (this.currentState === 'scanning' || this.currentState === 'starting') {
      return true;
    }

    this.setState('requesting-permissions');
    const perm = await requestBlePermissions();
    if (!perm.granted) {
      logger.warn('scanner', 'BLE permissions not granted', perm);
      this.callbacks.onError?.('Permission Bluetooth refusée');
      this.setState('error');
      return false;
    }

    this.setState('starting');
    try {
      if (!this.manager) {
        this.manager = new BleManager();
      }

      const state = await this.manager.state();
      if (state !== State.PoweredOn) {
        logger.warn('scanner', `BLE not powered on: ${state}`);
        this.stateSubscription?.remove();
        this.stateSubscription = this.manager.onStateChange((s) => {
          if (s === State.PoweredOn) {
            this.startDeviceScan();
          }
        }, true);
        return true;
      }

      this.startDeviceScan();
      return true;
    } catch (e) {
      logger.error('scanner', 'start failed', e);
      this.callbacks.onError?.(String(e));
      this.setState('error');
      return false;
    }
  }

  private startDeviceScan() {
    if (!this.manager) return;
    try {
      this.manager.startDeviceScan(null, { allowDuplicates: true }, (error, device) => {
        if (error) {
          logger.error('scanner', 'scan error', error);
          this.callbacks.onError?.(error.message);
          return;
        }
        if (!device) return;
        this.handleDevice(device);
      });
      this.setState('scanning');
      logger.info('scanner', 'BLE scan started');
    } catch (e) {
      logger.error('scanner', 'startDeviceScan threw', e);
      this.setState('error');
    }
  }

  private handleDevice(device: Device) {
    const identifier = this.extractIdentifier(device);
    if (!identifier) return;
    if (this.deviceFilter && !this.deviceFilter.includes(identifier)) return;

    // Throttle the same identifier to once every DEDUPE_WINDOW_MS.
    const now = Date.now();
    const last = this.dedupeMap.get(identifier) ?? 0;
    if (now - last < this.DEDUPE_WINDOW_MS) return;
    this.dedupeMap.set(identifier, now);

    const rssi = device.rssi ?? -100;
    this.callbacks.onDetection?.(identifier, rssi);
    enqueue({
      identifier,
      rssi,
      ts: new Date(now).toISOString(),
      platform: 'native',
    }).catch((e) => logger.warn('scanner', 'enqueue failed', e));
  }

  private extractIdentifier(device: Device): string | null {
    // Prefer the broadcast name; fall back to localName, then last 6 chars of mac id.
    if (device.name) return device.name;
    if (device.localName) return device.localName;
    if (device.id) return device.id.replace(/:/g, '').slice(-6).toUpperCase();
    return null;
  }

  async stop() {
    try {
      this.manager?.stopDeviceScan();
      this.stateSubscription?.remove();
      this.stateSubscription = null;
      this.dedupeMap.clear();
      this.setState('idle');
      logger.info('scanner', 'BLE scan stopped');
    } catch (e) {
      logger.warn('scanner', 'stop error', e);
    }
  }

  async destroy() {
    await this.stop();
    this.manager?.destroy();
    this.manager = null;
  }
}

export const bleScanner = new BleScanner();
