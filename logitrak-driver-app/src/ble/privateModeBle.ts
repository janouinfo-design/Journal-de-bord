import { BleManager, Device, State, Subscription } from 'react-native-ble-plx';
import { requestBlePermissions } from '@/utils/permissions';
import { logger } from '@/utils/logger';

/**
 * PHASE 1 — BLE READ-ONLY (FMC130 781479, device BLE « 781479_LE »).
 *
 * Objectif STRICT : prouver la connexion GATT réelle au FMC130 et LIRE l'état
 * Private/Business (Nordic UART Service). AUCUNE écriture `privatemode ON/OFF`.
 *
 * ⚠️ Cible terrain : FMC130 firmware **04.00.00_13** (BL:1.10, BT:4).
 * Les formats `:sec_login:` / `@sms_dbg:` NE sont PAS confirmés par le wiki public
 * Teltonika pour ce firmware. Cet écran est un OUTIL DE DIAGNOSTIC permettant de
 * tester plusieurs variantes (mode d'écriture, terminaison, format de commande) et
 * d'OBSERVER toutes les trames NOTIFY brutes, afin d'identifier la syntaxe réelle.
 *
 * Nordic UART :
 *   Service : 6e400001-... | Write (RX) : 6e400002-... | Notify (TX) : 6e400003-...
 *
 * Règles de sécurité : aucun secret loggé/persisté/hardcodé ; état = preuve réelle
 * du device (fail-closed). Mono-connexion FMC130 : stopper le scan beacon avant usage.
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
  /** Ligne reconnue "Privatemode ON/OFF" si trouvée (sûre à afficher). */
  rawResponse?: string | null;
  /** TOUTES les trames NOTIFY brutes reçues (sans filtrage) — diagnostic. */
  rawNotifications?: string | null;
  error?: string | null;
  /** Payload exact envoyé (secrets masqués, terminaison visible) — journal. */
  sentCommand?: string | null;
  /** Authentification keyword envoyée ? (keyword renseigné) */
  authSent?: boolean;
  /** Mode d'écriture réellement utilisé. */
  writeModeUsed?: BleWriteMode | null;
}

/** Format de commande Phase 1 (sélecteur UI). READ-ONLY : uniquement « privatemode ? ». */
export type BleCommandFormat = 'sms_dbg' | 'sms_std' | 'raw';

/** Terminaison de ligne (sélecteur UI). */
export type BleLineEnding = 'cr' | 'crlf' | 'lf' | 'none';

/** Mode d'écriture GATT (sélecteur UI). */
export type BleWriteMode = 'withResponse' | 'withoutResponse';

/** Capacités réelles de la caractéristique WRITE (lues après discovery). */
export interface BleWriteCaps {
  uuid: string;
  isWritableWithResponse: boolean;
  isWritableWithoutResponse: boolean;
}

export interface BleCredentials {
  /** :sec_login:<deviceKeyword> — OPTIONNEL : vide -> aucune authentification envoyée. */
  deviceKeyword?: string;
  /** login/password SMS — OPTIONNELS. */
  smsLogin?: string;
  smsPassword?: string;
  /** Format de la commande de lecture. Défaut : 'sms_std'. */
  format?: BleCommandFormat;
  /** Terminaison. Défaut : 'cr'. */
  lineEnding?: BleLineEnding;
  /** Mode d'écriture. Défaut : auto (selon capacités). */
  writeMode?: BleWriteMode;
}

/**
 * Construit la commande de LECTURE `privatemode ?` selon le format (PURE/testable).
 * - 'raw'     -> "privatemode ?"
 * - 'sms_std' -> format SMS Teltonika standard : "<login> <password> privatemode ?"
 *               SANS login/password -> DEUX espaces en tête : "  privatemode ?".
 * - 'sms_dbg' -> "@sms_dbg:[<login> <password> ]privatemode ?" (vide -> "@sms_dbg:privatemode ?").
 * READ-ONLY : jamais ON/OFF. Jamais de SMS réseau (envoi via BLE uniquement).
 */
export function buildReadCommand(
  format: BleCommandFormat | undefined,
  smsLogin?: string,
  smsPassword?: string,
): string {
  const login = (smsLogin || '').trim();
  const password = (smsPassword || '').trim();
  if (format === 'raw') return 'privatemode ?';
  if (format === 'sms_std') {
    // Format SMS/GPRS Teltonika : "<login> <password> <commande>".
    // Sans identifiants -> DEUX espaces en tête (exigence Teltonika documentée).
    return `${login} ${password} privatemode ?`;
  }
  // 'sms_dbg' (défaut historique)
  const auth = [login, password].filter(Boolean).join(' ');
  return auth ? `@sms_dbg:${auth} privatemode ?` : '@sms_dbg:privatemode ?';
}

/** Suffixe de terminaison à partir du sélecteur. */
export function lineEndingSuffix(ending: BleLineEnding | undefined): string {
  switch (ending) {
    case 'crlf': return '\r\n';
    case 'lf': return '\n';
    case 'none': return '';
    case 'cr':
    default: return '\r';
  }
}

/** Représentation LISIBLE du payload pour le journal (espaces/terminaison visibles). */
export function visualizePayload(payload: string): string {
  return payload
    .replace(/\r/g, '\\r')
    .replace(/\n/g, '\\n')
    .replace(/ /g, '·'); // espaces rendus visibles (ex: "··privatemode·?\\r")
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
  private writeCaps: BleWriteCaps | null = null;

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

  /** Connexion GATT + découverte services + lecture des capacités WRITE + activation notify. */
  async connect(deviceId: string): Promise<void> {
    if (!this.manager) this.manager = new BleManager();
    logger.info('ble-pm', `connect -> device ${deviceId}`);
    const dev = await this.manager.connectToDevice(deviceId, { timeout: CONNECT_TIMEOUT_MS });
    this.device = dev;
    await dev.discoverAllServicesAndCharacteristics();
    this.connected = true;

    // Lire les CAPACITÉS réelles de la caractéristique WRITE (diagnostic + choix du mode).
    this.writeCaps = null;
    try {
      const chars = await dev.characteristicsForService(NUS_SERVICE_UUID);
      const wc = chars.find((c) => c.uuid.toLowerCase() === NUS_WRITE_UUID.toLowerCase());
      if (wc) {
        this.writeCaps = {
          uuid: wc.uuid,
          isWritableWithResponse: !!wc.isWritableWithResponse,
          isWritableWithoutResponse: !!wc.isWritableWithoutResponse,
        };
      }
    } catch (e: any) {
      logger.warn('ble-pm', 'read write caps failed', e?.message);
    }

    // Activer les notifications AVANT tout envoi de commande. On conserve TOUT le buffer brut.
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
        logger.debug('ble-pm', 'notify chunk', visualizePayload(chunk));
      },
    );
  }

  /** Capacités WRITE lues au discovery (ou null). */
  getWriteCaps(): BleWriteCaps | null {
    return this.writeCaps;
  }

  /** Résout le mode d'écriture effectif selon le choix + les capacités réelles. */
  private resolveWriteMode(requested?: BleWriteMode): BleWriteMode {
    const caps = this.writeCaps;
    if (!caps) return requested ?? 'withoutResponse';
    if (requested === 'withResponse' && caps.isWritableWithResponse) return 'withResponse';
    if (requested === 'withoutResponse' && caps.isWritableWithoutResponse) return 'withoutResponse';
    // Auto / mode demandé non supporté -> prendre ce qui est réellement disponible.
    if (caps.isWritableWithoutResponse) return 'withoutResponse';
    if (caps.isWritableWithResponse) return 'withResponse';
    return requested ?? 'withoutResponse';
  }

  /**
   * Écrit une commande ASCII sur la caractéristique Write, avec terminaison et mode choisis.
   * Retourne le mode réellement utilisé (pour le journal).
   */
  private async writeCommand(
    ascii: string, ending: BleLineEnding | undefined, mode?: BleWriteMode,
  ): Promise<BleWriteMode> {
    if (!this.device) throw new Error('Non connecté');
    const full = `${ascii}${lineEndingSuffix(ending)}`;
    const payload = asciiToBase64(full);
    const effMode = this.resolveWriteMode(mode);
    logger.debug('ble-pm', `write [${effMode}]`, visualizePayload(redact(full)));
    if (effMode === 'withoutResponse') {
      await this.device.writeCharacteristicWithoutResponseForService(
        NUS_SERVICE_UUID, NUS_WRITE_UUID, payload);
    } else {
      await this.device.writeCharacteristicWithResponseForService(
        NUS_SERVICE_UUID, NUS_WRITE_UUID, payload);
    }
    return effMode;
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
   * Séquence READ-ONLY (diagnostic) :
   *   [:sec_login:<keyword> si keyword fourni]  ->  commande de lecture (format/terminaison/mode)
   * Keyword/login/password OPTIONNELS. Jamais d'écriture ON/OFF. Jamais de SMS réseau.
   * Retourne l'état + le payload exact (visualisé) + TOUTES les trames NOTIFY brutes.
   */
  async readPrivatemode(creds: BleCredentials): Promise<BleReadResult> {
    const keyword = (creds.deviceKeyword || '').trim();
    const authSent = keyword.length > 0;
    const cmd = buildReadCommand(creds.format, creds.smsLogin, creds.smsPassword);
    const ending = creds.lineEnding ?? 'cr';
    const sentVisual = visualizePayload(redact(`${cmd}${lineEndingSuffix(ending)}`));
    let writeModeUsed: BleWriteMode | null = null;
    try {
      // 1) Authentification device UNIQUEMENT si un keyword est renseigné.
      if (authSent) {
        await this.writeCommand(`:sec_login:${keyword}`, ending, creds.writeMode);
        await sleep(INTER_CMD_DELAY_MS);
      }

      // 2) Interrogation de l'état réel (READ-ONLY).
      writeModeUsed = await this.writeCommand(cmd, ending, creds.writeMode);

      // 3) Attendre une réponse reconnaissable (tout en conservant le buffer complet).
      const line = await this.waitForPrivatemode();
      const allRaw = this.buffer ? visualizePayload(this.buffer) : null;
      if (!line) {
        return { state: 'UNKNOWN', rawResponse: null, rawNotifications: allRaw,
                 error: 'Aucune ligne « Privatemode » reconnue (voir trames brutes).',
                 sentCommand: sentVisual, authSent, writeModeUsed };
      }
      const parsed = parsePrivatemodeResponse(line);
      if (!parsed) {
        return { state: 'UNKNOWN', rawResponse: line, rawNotifications: allRaw,
                 error: 'Réponse non reconnue.', sentCommand: sentVisual, authSent, writeModeUsed };
      }
      return { state: parsed, rawResponse: line, rawNotifications: allRaw, error: null,
               sentCommand: sentVisual, authSent, writeModeUsed };
    } catch (e: any) {
      logger.warn('ble-pm', 'readPrivatemode failed', e?.message);
      const allRaw = this.buffer ? visualizePayload(this.buffer) : null;
      return { state: 'ERROR', rawResponse: null, rawNotifications: allRaw,
               error: e?.message || 'Échec de lecture BLE.',
               sentCommand: sentVisual, authSent, writeModeUsed };
    }
  }

  /** Fermeture propre : :cfg_disconnect + cancel connexion + libération manager. */
  async disconnect(): Promise<void> {
    try {
      if (this.device && this.connected) {
        try { await this.writeCommand(':cfg_disconnect', 'cr'); } catch { /* best-effort */ }
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
