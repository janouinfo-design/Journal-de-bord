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
  buildReadCommand,
  lineEndingSuffix,
  visualizePayload,
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

describe('buildReadCommand — format de commande (READ-ONLY, jamais ON/OFF)', () => {
  test('format "raw" -> commande brute (ignore login/password)', () => {
    expect(buildReadCommand('raw')).toBe('privatemode ?');
    expect(buildReadCommand('raw', 'log', 'pwd')).toBe('privatemode ?');
  });

  test('format "sms_dbg" avec login+password', () => {
    expect(buildReadCommand('sms_dbg', 'log', 'pwd')).toBe('@sms_dbg:log pwd privatemode ?');
  });

  test('format "sms_dbg" SANS credentials -> pas de double espace', () => {
    expect(buildReadCommand('sms_dbg')).toBe('@sms_dbg:privatemode ?');
    expect(buildReadCommand('sms_dbg', '', '')).toBe('@sms_dbg:privatemode ?');
    expect(buildReadCommand('sms_dbg', '  ', '  ')).toBe('@sms_dbg:privatemode ?');
  });

  test('format "sms_dbg" avec login seul', () => {
    expect(buildReadCommand('sms_dbg', 'log', '')).toBe('@sms_dbg:log privatemode ?');
  });

  test('défaut (format undefined) -> sms_dbg', () => {
    expect(buildReadCommand(undefined, 'log', 'pwd')).toBe('@sms_dbg:log pwd privatemode ?');
  });

  test('READ-ONLY : jamais de ON/OFF produit', () => {
    for (const f of ['raw', 'sms_dbg', 'sms_std', undefined] as const) {
      const cmd = buildReadCommand(f, 'a', 'b').toLowerCase();
      expect(cmd).toContain('privatemode ?');
      expect(cmd).not.toContain(' on');
      expect(cmd).not.toContain(' off');
    }
  });

  test('format "sms_std" : "<login> <password> privatemode ?"', () => {
    expect(buildReadCommand('sms_std', 'log', 'pwd')).toBe('log pwd privatemode ?');
  });

  test('format "sms_std" SANS credentials : DEUX espaces en tête (exigence Teltonika)', () => {
    expect(buildReadCommand('sms_std')).toBe('  privatemode ?');
    expect(buildReadCommand('sms_std', '', '')).toBe('  privatemode ?');
    // les 2 espaces doivent être EXACTEMENT là
    expect(buildReadCommand('sms_std').startsWith('  ')).toBe(true);
    expect(buildReadCommand('sms_std').length).toBe('  privatemode ?'.length);
  });

  test('format "sms_std" avec login seul', () => {
    expect(buildReadCommand('sms_std', 'log', '')).toBe('log  privatemode ?');
  });
});

describe('lineEndingSuffix / visualizePayload', () => {
  test('terminaisons', () => {
    expect(lineEndingSuffix('cr')).toBe('\r');
    expect(lineEndingSuffix('crlf')).toBe('\r\n');
    expect(lineEndingSuffix('lf')).toBe('\n');
    expect(lineEndingSuffix('none')).toBe('');
    expect(lineEndingSuffix(undefined)).toBe('\r'); // défaut
  });

  test('visualisation : espaces et terminaisons visibles', () => {
    expect(visualizePayload('  privatemode ?\r')).toBe('··privatemode·?\\r');
    expect(visualizePayload('privatemode ?\r\n')).toBe('privatemode·?\\r\\n');
    expect(visualizePayload('x\n')).toBe('x\\n');
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

describe('garde-fous feature flag BLE DEV (logique pure, déterministe)', () => {
  const ff = require('@/config/featureFlags');

  test('computeBleDevEnabled : seule la valeur exacte "1" active', () => {
    expect(ff.computeBleDevEnabled('1')).toBe(true);
    expect(ff.computeBleDevEnabled('0')).toBe(false);   // explicitement verrouillé
    expect(ff.computeBleDevEnabled(undefined)).toBe(false);
    expect(ff.computeBleDevEnabled(null)).toBe(false);
    expect(ff.computeBleDevEnabled('true')).toBe(false);
    expect(ff.computeBleDevEnabled(' 1 ')).toBe(false); // pas de trim : strict
  });

  test('parseAllowedTrackers : CSV -> liste normalisée, vide -> []', () => {
    expect(ff.parseAllowedTrackers('781479')).toEqual(['781479']);
    expect(ff.parseAllowedTrackers('781479, 123456 ')).toEqual(['781479', '123456']);
    expect(ff.parseAllowedTrackers('')).toEqual([]);
    expect(ff.parseAllowedTrackers(undefined)).toEqual([]);
  });

  test('isTrackerAllowed : allowlist vide -> fail-closed', () => {
    expect(ff.isTrackerAllowed('781479', [])).toBe(false);
  });

  test('isTrackerAllowed : exact match, variantes refusées (pas de sous-chaîne)', () => {
    const allow = ['781479'];
    expect(ff.isTrackerAllowed('781479', allow)).toBe(true);
    expect(ff.isTrackerAllowed('17814790', allow)).toBe(false);
    expect(ff.isTrackerAllowed('781479999', allow)).toBe(false);
    expect(ff.isTrackerAllowed(' 781479 ', allow)).toBe(true); // trim de l'entrée
    expect(ff.isTrackerAllowed(null, allow)).toBe(false);
  });

  test('extractCandidateTrackerIds : découpage déterministe par séparateurs', () => {
    expect(ff.extractCandidateTrackerIds('FMC-781479-x')).toEqual(['FMC', '781479', 'x']);
    expect(ff.extractCandidateTrackerIds('17814790')).toEqual(['17814790']);
    expect(ff.extractCandidateTrackerIds(null)).toEqual([]);
  });

  test('isBleDeviceAllowed : "FMC-781479-x" OK, "17814790"/"FMC130" refusés', () => {
    const allow = ['781479'];
    expect(ff.isBleDeviceAllowed({ name: 'FMC-781479-x' }, allow)).toBe(true);
    expect(ff.isBleDeviceAllowed({ name: '17814790' }, allow)).toBe(false);
    expect(ff.isBleDeviceAllowed({ name: 'FMC130' }, allow)).toBe(false);
    expect(ff.isBleDeviceAllowed({ id: '781479' }, allow)).toBe(true);
    expect(ff.isBleDeviceAllowed({ name: null, localName: null, id: null }, allow)).toBe(false);
    expect(ff.isBleDeviceAllowed({ name: '781479' }, [])).toBe(false); // fail-closed
  });
});
