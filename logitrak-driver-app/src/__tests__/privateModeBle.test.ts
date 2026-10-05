/**
 * Tests Phase 1 BLE READ-ONLY — logique pure (sans device réel).
 *
 * Couvre :
 * - parsing fail-closed de `privatemode ?` (ON -> PRIVATE, OFF -> PRO, sinon null) ;
 * - round-trip base64 (encodage commande / décodage réponse) ;
 * - garantie qu'AUCUN secret n'apparaît dans les logs (redaction).
 *
 * Le module ne doit PAS envoyer `privatemode ON/OFF` : on vérifie l'absence d'API d'écriture d'état.
 */
import {
  parsePrivatemodeResponse,
  asciiToBase64,
  base64ToAscii,
  NUS_SERVICE_UUID,
  NUS_WRITE_UUID,
  NUS_NOTIFY_UUID,
} from '@/ble/privateModeBle';

describe('parsePrivatemodeResponse — fail-closed', () => {
  test('Privatemode ON -> PRIVATE', () => {
    expect(parsePrivatemodeResponse('Privatemode ON')).toBe('PRIVATE');
    expect(parsePrivatemodeResponse('privatemode on\r')).toBe('PRIVATE');
    expect(parsePrivatemodeResponse('  PRIVATEMODE ON  ')).toBe('PRIVATE');
  });

  test('Privatemode OFF -> PRO', () => {
    expect(parsePrivatemodeResponse('Privatemode OFF')).toBe('PRO');
    expect(parsePrivatemodeResponse('privatemode off\r\n')).toBe('PRO');
  });

  test('variantes :0 / :1', () => {
    expect(parsePrivatemodeResponse('privatemode:1')).toBe('PRIVATE');
    expect(parsePrivatemodeResponse('privatemode:0')).toBe('PRO');
  });

  test('réponse vide / null / bruit -> null (jamais supposé)', () => {
    expect(parsePrivatemodeResponse(null)).toBeNull();
    expect(parsePrivatemodeResponse(undefined)).toBeNull();
    expect(parsePrivatemodeResponse('')).toBeNull();
    expect(parsePrivatemodeResponse('ERROR: unknown command')).toBeNull();
    expect(parsePrivatemodeResponse('login ok')).toBeNull();
    // mention de privatemode sans valeur reconnaissable -> null
    expect(parsePrivatemodeResponse('privatemode ?')).toBeNull();
  });
});

describe('base64 round-trip (ASCII)', () => {
  test('encode puis décode = identité', () => {
    const samples = [
      ':sec_login:KEYWORD123',
      '@sms_dbg:login secret privatemode ?\r',
      'Privatemode ON\r',
      'Privatemode OFF\r',
      ':cfg_disconnect\r',
    ];
    for (const s of samples) {
      expect(base64ToAscii(asciiToBase64(s))).toBe(s);
    }
  });

  test('décode une trame notify simulée', () => {
    const b64 = asciiToBase64('Privatemode OFF\r');
    expect(parsePrivatemodeResponse(base64ToAscii(b64))).toBe('PRO');
  });
});

describe('UUIDs Nordic UART (Teltonika)', () => {
  test('service/write/notify conformes à la fiche Teltonika', () => {
    expect(NUS_SERVICE_UUID).toBe('6e400001-b5a3-f393-e0a9-e50e24dcca9e');
    expect(NUS_WRITE_UUID).toBe('6e400002-b5a3-f393-e0a9-e50e24dcca9e');
    expect(NUS_NOTIFY_UUID).toBe('6e400003-b5a3-f393-e0a9-e50e24dcca9e');
  });
});

describe('sécurité — pas d\'écriture d\'état en Phase 1', () => {
  test('le module n\'exporte aucune API ON/OFF', () => {
    const api = require('@/ble/privateModeBle');
    const names = Object.keys(api);
    // Aucune fonction d'écriture d'état exposée (ex: setPrivate, writePrivatemodeOn...).
    for (const n of names) {
      expect(/setprivate|privatemodeon|privatemodeoff|writemode|turnon|turnoff/i.test(n)).toBe(false);
    }
  });
});
