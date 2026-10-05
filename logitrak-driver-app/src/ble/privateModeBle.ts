import { BleManager, Device, State, Subscription } from 'react-native-ble-plx';
import { requestBlePermissions } from '@/utils/permissions';
import { logger } from '@/utils/logger';

/**
 * PHASE 1 — BLE READ-ONLY (FMC130 781479).
 *
 * Objectif STRICT : prouver la connexion GATT réelle au FMC130 et LIRE l'état
 * Private/Business via `privatemode ?` (Nordic UART Service). AUCUNE écriture
 * `privatemode ON/OFF` ici.
 *
 * Source Teltonika (firmware 04.02.03.Rev.01) :
 *   Service : 6e400001-b5a3-f393-e0a9-e50e24dcca9e
 *   Write   : 6e400002-b5a3-f393-e0a9-e50e24dcca9e  (vers le device)
 *   Notify  : 6e400003-b5a3-f393-e0a9-e50e24dcca9e  (réponses du device)
 *   Commandes ASCII terminées par '\r'.
 *   Workflow : connexion -> activer notify -> :sec_login:<keyword> ->
 *              @sms_dbg:<login> <password> privatemode ? -> lire "Privatemode ON/OFF"
 *              -> :cfg_disconnect
 *
 * Règles de sécurité (impératives) :
 * - AUCUN secret (keyword/login/password) n'est jamais écrit dans les logs.
 * - AUCUN secret n'est persisté ici (les credentials viennent de l'appelant, en mémoire).
 * - AUCUN secret hardcodé.
 * - La preuve d'état = réponse réelle du device (fail-closed : sinon UNKNOWN/ERROR).
 *
 * NOTE mono-connexion : le FMC130 n'accepte qu'UNE connexion BLE à la fois. L'appelant
 * DOIT mettre en pause le scan beacon (bleScanner.stop()) avant d'utiliser ce module.
 */

// ---- UUIDs Nordic UART Service (Teltonika) ----
export const NUS_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
export const NUS_WRITE_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
export const NUS_NOTIFY_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';

// ---- États techniques exposés à l'UI DEV ----
export type BlePrivateModeState =
  | 'UNKNOWN'
  | 'CONNECTING'
  | 'PRO'       // Privatemode OFF confirmé par le device
  | 'PRIVATE'   // Privatemode ON confirmé par le device
  | 'ERROR';

export interface BleReadResult {
  state: BlePrivateModeState;
  /** Ligne brute renvoyée par le device (SANS secret ; sûre à afficher en DEV). */
  rawResponse?: string | null;
  error?: string | null;
}

export interface BleCredentials {
  /** :sec_login:<deviceKeyword> */
  deviceKeyword: string;
  /** @sms_dbg:<smsLogin> <smsPassword> privatemode ? */
  smsLogin: string;
  smsPassword: string;
}

/** Délais (ms) — bornés pour éviter tout spinner infini. */
const CONNECT_TIMEOUT_MS = 12_000;
const RESPONSE_TIMEOUT_MS = 8_000;
const INTER_CMD_DELAY_MS = 400;

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

// --- base64 minimal (ble-plx exige du base64 ; aucune dépendance ajoutée) ---
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

export function asciiToBase64(input: string): string {
  let out = '';
  let i = 0;
  while (i < input.length) {
    const c1 = input.charCodeAt(i++) & 0xff;
    const c2 = i < input.length ? input.charCodeAt(i++) & 0xff : NaN;
    const c3 = i < input.length ? input.charCodeAt(i++) & 0xff : NaN;
    const e1 = c1 >> 2;
    const e2 = ((c1 & 3) << 4) | (c2 >> 4);
    let e3 = ((c2 & 15) << 2) | (c3 >> 6);
    let e4 = c3 & 63;
    if (Number.isNaN(c2)) { e3 = 64; e4 = 64; }
    else if (Number.isNaN(c3)) { e4 = 64; }
    out += B64.charAt(e1) + B64.charAt(e2) +
      (e3 === 64 ? '=' : B64.charAt(e3)) +
      (e4 === 64 ? '=' : B64.charAt(e4));
  }
  return out;
}

export function base64ToAscii(input: string): string {
  const clean = (input || '').replace(/[^A-Za-z0-9+/=]/g, '');
  let out = '';
  let i = 0;
  while (i < clean.length) {
    const d1 = B64.indexOf(clean.charAt(i++));
    const d2 = B64.indexOf(clean.charAt(i++));
    const d3 = B64.indexOf(clean.charAt(i++));
    const d4 = B64.indexOf(clean.charAt(i++));
    const c1 = (d1 << 2) | (d2 >> 4);
    const c2 = ((d2 & 15) << 4) | (d3 >> 2);
    const c3 = ((d3 & 3) << 6) | d4;
    out += String.fromCharCode(c1);
    if (d3 !== 64 && d3 !== -1) out += String.fromCharCode(c2);
    if (d4 !== 64 && d4 !== -1) out += String.fromCharCode(c3);
  }
  return out;
}

/**
 * Interprète une ligne device en état Private/Business.
 * Fail-closed : toute réponse non reconnue -> null (jamais d'état supposé).
 * Insensible à la casse / aux espaces. Gère "Privatemode ON", "privatemode:1", etc.
 */
export function parsePrivatemodeResponse(raw: string | null | undefined): BlePrivateModeState | null {
  if (!raw) return null;
  const t = raw.toLowerCase();
  // ON -> PRIVATE
  if (t.includes('privatemode on') || t.includes('privatemode:1') || t.includes('privatemode 1')) {
    return 'PRIVATE';
  }
  // OFF -> PRO
  if (t.includes('privatemode off') || t.includes('privatemode:0') || t.includes('privatemode 0')) {
    return 'PRO';
  }
  return null;
}

/** Masque toute trace de secret dans une chaîne destinée aux logs. */
function redact(line: string): string {
  // Retire tout ce qui suit @sms_dbg: et :sec_login: (login/password/keyword).
  return line
    .replace(/(@sms_dbg:)[^\r\n]*/gi, '$1***')
    .replace(/(:sec_login:)[^\r\n]*/gi, '$1***');
}

export class PrivateModeBleReader {
  private manager: BleManager | null = null;
  private device: Device | null = null;
  private notifySub: Subscription | null = null;
  private buffer = '';
  private connected = false;

  /** Scanne et retourne les devices dont le nom correspond à `nameFilter` (ex: contient "781479"). */
  async findDevice(nameFilter: string, timeoutMs = CONNECT_TIMEOUT_MS): Promise<Device | null> {
    const perm = await requestBlePermissions();
    if (!perm.granted) throw new Error('Permission Bluetooth refusée');
    if (!this.manager) this.manager = new BleManager();

    const st = await this.manager.state();
    if (st !== State.PoweredOn) throw new Error('Bluetooth non activé');

    const filterLower = (nameFilter || '').toLowerCase();
    return new Promise<Device | null>((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        this.manager?.stopDeviceScan();
        resolve(null);
      }, timeoutMs);

      this.manager!.startDeviceScan(null, { allowDuplicates: false }, (error, dev) => {
        if (error) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          this.manager?.stopDeviceScan();
          reject(new Error(error.message));
          return;
        }
        const name = (dev?.name || dev?.localName || '').toLowerCase();
        if (dev && filterLower && name.includes(filterLower)) {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          this.manager?.stopDeviceScan();
          resolve(dev);
        }
      });
    });
  }

  /** Connexion GATT + découverte services + activation des notifications. */
  async connect(deviceId: string): Promise<void> {
    if (!this.manager) this.manager = new BleManager();
    logger.info('ble-pm', `connect -> device ${deviceId}`);
    const dev = await this.manager.connectToDevice(deviceId, { timeout: CONNECT_TIMEOUT_MS });
    this.device = dev;
    await dev.discoverAllServicesAndCharacteristics();
    this.connected = true;

    // Activer les notifications AVANT tout envoi de commande (exigé par le workflow).
    this.buffer = '';
    this.notifySub = dev.monitorCharacteristicForService(
      NUS_SERVICE_UUID,
      NUS_NOTIFY_UUID,
      (err, characteristic) => {
        if (err) {
          logger.warn('ble-pm', 'notify error', err.message);
          return;
        }
        const b64 = characteristic?.value;
        if (!b64) return;
        const chunk = base64ToAscii(b64);
        this.buffer += chunk;
        logger.debug('ble-pm', 'notify chunk', redact(chunk.replace(/\r/g, '\\r')));
      },
    );
  }

  /** Écrit une commande ASCII (terminée par \r) sur la caractéristique Write. */
  private async writeCommand(ascii: string): Promise<void> {
    if (!this.device) throw new Error('Non connecté');
    const payload = asciiToBase64(ascii.endsWith('\r') ? ascii : `${ascii}\r`);
    logger.debug('ble-pm', 'write', redact(ascii));
    await this.device.writeCharacteristicWithResponseForService(
      NUS_SERVICE_UUID,
      NUS_WRITE_UUID,
      payload,
    );
  }

  /** Attend qu'une réponse reconnaissable (ON/OFF) apparaisse dans le buffer, borné par timeout. */
  private async waitForPrivatemode(timeoutMs = RESPONSE_TIMEOUT_MS): Promise<string | null> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const line = this.extractPrivatemodeLine();
      if (line) return line;
      await sleep(150);
    }
    return null;
  }

  /** Cherche dans le buffer une ligne contenant "Privatemode ...". Ne renvoie jamais de secret. */
  private extractPrivatemodeLine(): string | null {
    const lines = this.buffer.split(/[\r\n]+/);
    for (const l of lines) {
      if (/privatemode/i.test(l) && /(on|off|:0|:1|\s0|\s1)/i.test(l)) {
        return l.trim();
      }
    }
    return null;
  }

  /**
   * Séquence READ-ONLY complète :
   *   :sec_login:<keyword>  ->  @sms_dbg:<login> <password> privatemode ?  ->  lecture ON/OFF
   * Retourne l'état confirmé par le device, ou ERROR/UNKNOWN (fail-closed).
   */
  async readPrivatemode(creds: BleCredentials): Promise<BleReadResult> {
    try {
      // 1) Authentification device (keyword). Secret jamais loggé.
      await this.writeCommand(`:sec_login:${creds.deviceKeyword}`);
      await sleep(INTER_CMD_DELAY_MS);

      // 2) Interrogation de l'état réel.
      await this.writeCommand(`@sms_dbg:${creds.smsLogin} ${creds.smsPassword} privatemode ?`);

      // 3) Attendre une réponse reconnaissable.
      const line = await this.waitForPrivatemode();
      if (!line) {
        return { state: 'UNKNOWN', rawResponse: null, error: 'Aucune réponse du véhicule (timeout).' };
      }
      const parsed = parsePrivatemodeResponse(line);
      if (!parsed) {
        return { state: 'UNKNOWN', rawResponse: line, error: 'Réponse non reconnue.' };
      }
      return { state: parsed, rawResponse: line, error: null };
    } catch (e: any) {
      logger.warn('ble-pm', 'readPrivatemode failed', e?.message);
      return { state: 'ERROR', rawResponse: null, error: e?.message || 'Échec de lecture BLE.' };
    }
  }

  /** Fermeture propre : :cfg_disconnect + cancel connexion + libération manager. */
  async disconnect(): Promise<void> {
    try {
      if (this.device && this.connected) {
        try { await this.writeCommand(':cfg_disconnect'); } catch { /* best-effort */ }
      }
    } finally {
      try { this.notifySub?.remove(); } catch { /* ignore */ }
      this.notifySub = null;
      try {
        if (this.device) await this.manager?.cancelDeviceConnection(this.device.id);
      } catch { /* ignore */ }
      this.device = null;
      this.connected = false;
      this.buffer = '';
    }
  }

  /** Détruit le manager BLE (à appeler au démontage de l'écran DEV). */
  async destroy(): Promise<void> {
    await this.disconnect();
    try { this.manager?.destroy(); } catch { /* ignore */ }
    this.manager = null;
  }
}
