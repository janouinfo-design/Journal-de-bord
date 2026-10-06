import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, radius, font } from '@/theme/colors';
import {
  PrivateModeBleReader, BlePrivateModeState, BleReadResult,
  BleCommandFormat, BleLineEnding, BleWriteMode,
} from '@/ble/privateModeBle';
import { bleScanner } from '@/ble/scanner';
import { isBleDeviceAllowedForDev, BLE_DEV_ALLOWED_TRACKERS } from '@/config/featureFlags';

/**
 * ÉCRAN DEV — PHASE 1 BLE READ-ONLY (FMC130 781479, device « 781479_LE »).
 * Outil de DIAGNOSTIC : teste format / terminaison / mode d'écriture et journalise
 * TOUTES les trames NOTIFY brutes. AUCUNE écriture ON/OFF. Zéro backend. Zéro SMS réseau.
 * Cible firmware : 04.00.00_13.
 */

const STATE_LABEL: Record<BlePrivateModeState, string> = {
  UNKNOWN: 'Inconnu',
  CONNECTING: 'Connexion…',
  PRO: 'PROFESSIONNEL (Privatemode OFF)',
  PRIVATE: 'PRIVÉ (Privatemode ON)',
  ERROR: 'Erreur',
};

const STATE_COLOR: Record<BlePrivateModeState, string> = {
  UNKNOWN: colors.textMuted,
  CONNECTING: colors.warning,
  PRO: colors.pro,
  PRIVATE: colors.perso,
  ERROR: colors.danger,
};

const FORMAT_OPTIONS: { value: BleCommandFormat; label: string }[] = [
  { value: 'sms_std', label: 'SMS std (2 esp.)' },
  { value: 'raw', label: 'brut' },
  { value: 'sms_dbg', label: '@sms_dbg' },
];

const ENDING_OPTIONS: { value: BleLineEnding; label: string }[] = [
  { value: 'cr', label: '\\r' },
  { value: 'crlf', label: '\\r\\n' },
  { value: 'lf', label: '\\n' },
  { value: 'none', label: 'aucune' },
];

const WRITE_OPTIONS: { value: BleWriteMode; label: string }[] = [
  { value: 'withoutResponse', label: 'Sans réponse' },
  { value: 'withResponse', label: 'Avec réponse' },
];

export default function BlePrivateModeDevScreen() {
  const [nameFilter, setNameFilter] = useState(BLE_DEV_ALLOWED_TRACKERS[0] ?? '');
  const [deviceKeyword, setDeviceKeyword] = useState('');
  const [smsLogin, setSmsLogin] = useState('');
  const [smsPassword, setSmsPassword] = useState('');
  const [format, setFormat] = useState<BleCommandFormat>('sms_std');
  const [lineEnding, setLineEnding] = useState<BleLineEnding>('cr');
  const [writeMode, setWriteMode] = useState<BleWriteMode>('withoutResponse');
  const [state, setState] = useState<BlePrivateModeState>('UNKNOWN');
  const [busy, setBusy] = useState(false);
  const [raw, setRaw] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const readerRef = useRef<PrivateModeBleReader | null>(null);

  const appendLog = useCallback((line: string) => {
    setLog((prev) => [...prev.slice(-40), `${new Date().toLocaleTimeString('fr-CH')} ${line}`]);
  }, []);

  useEffect(() => {
    return () => { readerRef.current?.destroy().catch(() => {}); };
  }, []);

  const run = useCallback(async () => {
    if (busy) return;
    // Credentials TOUS optionnels. Aucune exigence bloquante.
    setBusy(true);
    setError(null);
    setRaw(null);
    setState('CONNECTING');
    appendLog(`Format : ${format} | Terminaison : ${lineEnding} | Write : ${writeMode}`);
    appendLog('Pause du scan beacon (mono-connexion FMC130)…');
    try { await bleScanner.stop(); } catch { /* ignore */ }

    const reader = new PrivateModeBleReader();
    readerRef.current = reader;
    let result: BleReadResult = { state: 'ERROR' };
    try {
      appendLog(`Recherche du véhicule « ${nameFilter} »…`);
      const dev = await reader.findDevice(nameFilter);
      if (!dev) {
        setState('ERROR');
        setError('Véhicule introuvable (vérifiez le filtre de nom et la proximité).');
        appendLog('Aucun device trouvé.');
        return;
      }
      const detectedName = dev.name || dev.localName || dev.id;
      appendLog(`Nom BLE détecté : « ${detectedName} » | RSSI : ${dev.rssi ?? 'n/a'} dBm.`);
      if (!isBleDeviceAllowedForDev({ name: dev.name, localName: dev.localName, id: dev.id })) {
        setState('ERROR');
        setError(
          `Périphérique détecté non autorisé. Autorisés : ${
            BLE_DEV_ALLOWED_TRACKERS.join(', ') || '(aucun)'
          }.`,
        );
        appendLog('Refus de connexion : device détecté hors allowlist.');
        return;
      }
      appendLog('Device autorisé. Connexion GATT…');
      await reader.connect(dev.id);

      // Journal : capacités réelles de la caractéristique WRITE.
      const caps = reader.getWriteCaps();
      if (caps) {
        appendLog(`WRITE char ${caps.uuid} | WithResponse=${caps.isWritableWithResponse} | WithoutResponse=${caps.isWritableWithoutResponse}`);
      } else {
        appendLog('Capacités WRITE : indéterminées (char introuvable au discovery).');
      }
      appendLog('Connecté. Notifications activées.');

      result = await reader.readPrivatemode({
        deviceKeyword, smsLogin, smsPassword, format, lineEnding, writeMode,
      });
      appendLog(`Auth keyword : ${result.authSent ? 'ENVOYÉE' : 'NON envoyée (vide)'}.`);
      appendLog(`Write mode utilisé : ${result.writeModeUsed ?? 'n/a'}.`);
      appendLog(`Payload exact envoyé : « ${result.sentCommand ?? '(n/a)'} »`);
      appendLog(`Trames NOTIFY brutes : ${result.rawNotifications ? `« ${result.rawNotifications} »` : '(aucune)'}`);
      setState(result.state);
      setRaw(result.rawResponse ?? null);
      if (result.error) setError(result.error);
      appendLog(`Résultat : ${result.state}${result.error ? ` — ${result.error}` : ''}`);
    } catch (e: any) {
      setState('ERROR');
      setError(e?.message || 'Échec BLE.');
      appendLog(`Erreur GATT : ${e?.message || 'inconnue'}`);
    } finally {
      try { await reader.disconnect(); appendLog('Déconnexion propre.'); } catch { /* ignore */ }
      setBusy(false);
    }
  }, [busy, deviceKeyword, smsLogin, smsPassword, nameFilter, format, lineEnding, writeMode, appendLog]);

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content} testID="ble-dev-scroll">
        <Text style={styles.title}>BLE Private Mode — DEV (diagnostic, lecture seule)</Text>
        <Text style={styles.sub}>
          Phase 1 : connexion GATT au FMC130 (fw 04.00.00_13) et lecture « privatemode ? ».
          Aucune écriture ON/OFF. Credentials en mémoire uniquement.
        </Text>

        <View style={[styles.stateCard, { borderColor: STATE_COLOR[state] }]} testID="ble-dev-state">
          <Text style={styles.stateLabel}>État lu</Text>
          <Text style={[styles.stateValue, { color: STATE_COLOR[state] }]} testID="ble-dev-state-value">
            {STATE_LABEL[state]}
          </Text>
          {raw ? <Text style={styles.rawLine} testID="ble-dev-raw">Réponse : {raw}</Text> : null}
          {error ? <Text style={styles.errorLine} testID="ble-dev-error">{error}</Text> : null}
        </View>

        <Text style={styles.field}>Filtre nom device (ex : 781479)</Text>
        <TextInput
          style={styles.input} value={nameFilter} onChangeText={setNameFilter}
          autoCapitalize="none" autoCorrect={false} testID="ble-dev-name"
        />

        <Text style={styles.field}>Format de commande</Text>
        <Selector
          options={FORMAT_OPTIONS} value={format} onChange={setFormat} testPrefix="ble-dev-format"
        />

        <Text style={styles.field}>Terminaison</Text>
        <Selector
          options={ENDING_OPTIONS} value={lineEnding} onChange={setLineEnding} testPrefix="ble-dev-ending"
        />

        <Text style={styles.field}>Mode d'écriture (prioriser « Sans réponse »)</Text>
        <Selector
          options={WRITE_OPTIONS} value={writeMode} onChange={setWriteMode} testPrefix="ble-dev-write"
        />

        <Text style={styles.field}>Device keyword (:sec_login) — optionnel</Text>
        <TextInput
          style={styles.input} value={deviceKeyword} onChangeText={setDeviceKeyword}
          placeholder="Laisser vide = pas d'authentification"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none" autoCorrect={false} secureTextEntry testID="ble-dev-keyword"
        />
        <Text style={styles.field}>SMS login — optionnel</Text>
        <TextInput
          style={styles.input} value={smsLogin} onChangeText={setSmsLogin}
          placeholder="Optionnel" placeholderTextColor={colors.textMuted}
          autoCapitalize="none" autoCorrect={false} testID="ble-dev-login"
          editable={format !== 'raw'}
        />
        <Text style={styles.field}>SMS password — optionnel</Text>
        <TextInput
          style={styles.input} value={smsPassword} onChangeText={setSmsPassword}
          placeholder="Optionnel" placeholderTextColor={colors.textMuted}
          autoCapitalize="none" autoCorrect={false} secureTextEntry testID="ble-dev-password"
          editable={format !== 'raw'}
        />

        <TouchableOpacity
          style={[styles.btn, busy && styles.btnDisabled]}
          onPress={run} disabled={busy} testID="ble-dev-read"
          accessibilityRole="button" accessibilityLabel="Lire l'état BLE"
        >
          {busy ? <ActivityIndicator color={colors.textInverse} />
            : <Text style={styles.btnText}>Lire l'état (privatemode ?)</Text>}
        </TouchableOpacity>

        <Text style={styles.field}>Journal technique</Text>
        <View style={styles.logBox} testID="ble-dev-log">
          {log.length === 0 ? <Text style={styles.logEmpty}>—</Text>
            : log.map((l, i) => <Text key={i} style={styles.logLine}>{l}</Text>)}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

/** Petit sélecteur segmenté générique (diagnostic). */
function Selector<T extends string>({ options, value, onChange, testPrefix }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  testPrefix: string;
}) {
  return (
    <View style={styles.selectorRow}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <TouchableOpacity
            key={o.value}
            style={[styles.selectorBtn, active && styles.selectorBtnActive]}
            onPress={() => onChange(o.value)}
            testID={`${testPrefix}-${o.value}`}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
          >
            <Text style={[styles.selectorText, active && styles.selectorTextActive]}>{o.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  title: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', marginBottom: spacing.xs },
  sub: { color: colors.textMuted, fontSize: font.size.sm, marginBottom: spacing.lg, lineHeight: 18 },
  stateCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 2,
    padding: spacing.lg, marginBottom: spacing.lg,
  },
  stateLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase', letterSpacing: 1 },
  stateValue: { fontSize: font.size.lg, fontWeight: '700', marginTop: spacing.xs },
  rawLine: { color: colors.text, fontSize: font.size.sm, marginTop: spacing.sm },
  errorLine: { color: colors.danger, fontSize: font.size.sm, marginTop: spacing.sm },
  field: { color: colors.textMuted, fontSize: font.size.xs, marginTop: spacing.md, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 1 },
  input: {
    backgroundColor: colors.bgCard, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    color: colors.text, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, fontSize: font.size.md,
  },
  selectorRow: { flexDirection: 'row', gap: spacing.xs, flexWrap: 'wrap' },
  selectorBtn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingVertical: spacing.xs, paddingHorizontal: spacing.md, backgroundColor: colors.bgCard,
  },
  selectorBtnActive: { borderColor: colors.primary, backgroundColor: colors.primary + '22' },
  selectorText: { color: colors.textMuted, fontSize: font.size.sm, fontWeight: '600' },
  selectorTextActive: { color: colors.primary },
  btn: {
    marginTop: spacing.lg, backgroundColor: colors.primary, borderRadius: radius.md,
    paddingVertical: spacing.md, alignItems: 'center',
  },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: colors.textInverse, fontSize: font.size.md, fontWeight: '700' },
  logBox: {
    backgroundColor: colors.bgCard, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.sm, marginTop: 4, minHeight: 80,
  },
  logEmpty: { color: colors.textMuted, fontSize: font.size.sm },
  logLine: { color: colors.textMuted, fontSize: font.size.xs, lineHeight: 16 },
});
