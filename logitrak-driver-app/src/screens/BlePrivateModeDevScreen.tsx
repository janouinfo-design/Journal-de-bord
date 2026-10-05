import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, radius, font } from '@/theme/colors';
import {
  PrivateModeBleReader, BlePrivateModeState, BleReadResult, BleCommandFormat,
} from '@/ble/privateModeBle';
import { bleScanner } from '@/ble/scanner';
import { isBleDeviceAllowedForDev, BLE_DEV_ALLOWED_TRACKERS } from '@/config/featureFlags';

/**
 * ÉCRAN DEV — PHASE 1 BLE READ-ONLY (FMC130 781479).
 *
 * But : prouver la connexion GATT réelle + lecture `privatemode ?`.
 * - Credentials saisis EN MÉMOIRE uniquement (jamais persistés, jamais loggés).
 * - AUCUNE écriture `privatemode ON/OFF`.
 * - Met en PAUSE le scan beacon pendant la connexion (mono-connexion FMC130).
 * - Accès réservé au DEV (routé derrière le flag PRIVATE_MODE_BLE_DEV).
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

export default function BlePrivateModeDevScreen() {
  const [nameFilter, setNameFilter] = useState(BLE_DEV_ALLOWED_TRACKERS[0] ?? '');
  const [deviceKeyword, setDeviceKeyword] = useState('');
  const [smsLogin, setSmsLogin] = useState('');
  const [smsPassword, setSmsPassword] = useState('');
  const [format, setFormat] = useState<BleCommandFormat>('sms_dbg');
  const [state, setState] = useState<BlePrivateModeState>('UNKNOWN');
  const [busy, setBusy] = useState(false);
  const [raw, setRaw] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const readerRef = useRef<PrivateModeBleReader | null>(null);

  const appendLog = useCallback((line: string) => {
    setLog((prev) => [...prev.slice(-30), `${new Date().toLocaleTimeString('fr-CH')} ${line}`]);
  }, []);

  useEffect(() => {
    return () => {
      // Démontage : on libère la connexion et le manager, et on ne laisse rien ouvert.
      readerRef.current?.destroy().catch(() => {});
    };
  }, []);

  const run = useCallback(async () => {
    if (busy) return;
    // Credentials TOUS optionnels (keyword/login/password). Aucune exigence bloquante.
    setBusy(true);
    setError(null);
    setRaw(null);
    setState('CONNECTING');
    appendLog(`Format sélectionné : ${format === 'raw' ? 'privatemode ? (brut)' : '@sms_dbg:[login password] privatemode ?'}`);
    appendLog('Pause du scan beacon (mono-connexion FMC130)…');

    // Mono-connexion : le FMC130 n'accepte qu'UNE connexion BLE. On stoppe le scan.
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
      // Journal technique : nom BLE réellement détecté + RSSI (donnée clé terrain).
      const detectedName = dev.name || dev.localName || dev.id;
      appendLog(`Nom BLE détecté : « ${detectedName} » | RSSI : ${dev.rssi ?? 'n/a'} dBm (à confirmer terrain).`);
      // GARDE-FOU (pilote) : contrôle de l'IDENTIFIANT RÉELLEMENT DÉTECTÉ (pas le texte saisi).
      if (!isBleDeviceAllowedForDev({ name: dev.name, localName: dev.localName, id: dev.id })) {
        setState('ERROR');
        setError(
          `Périphérique détecté non autorisé pour ce test DEV. Autorisés : ${
            BLE_DEV_ALLOWED_TRACKERS.join(', ') || '(aucun)'
          }.`,
        );
        appendLog('Refus de connexion : device détecté hors allowlist.');
        return;
      }
      appendLog(`Device autorisé. Connexion GATT…`);
      await reader.connect(dev.id);
      appendLog('Connecté. Notifications activées.');

      result = await reader.readPrivatemode({ deviceKeyword, smsLogin, smsPassword, format });
      appendLog(`Authentification keyword : ${result.authSent ? 'ENVOYÉE' : 'NON envoyée (keyword vide)'}.`);
      appendLog(`Commande envoyée : « ${result.sentCommand ?? '(n/a)'} »`);
      appendLog(`Réponse brute : ${result.rawResponse ? `« ${result.rawResponse} »` : '(aucune)'}`);
      setState(result.state);
      setRaw(result.rawResponse ?? null);
      if (result.error) setError(result.error);
      appendLog(`Résultat : ${result.state}${result.error ? ` — ${result.error}` : ''}`);
    } catch (e: any) {
      setState('ERROR');
      setError(e?.message || 'Échec BLE.');
      appendLog(`Erreur GATT : ${e?.message || 'inconnue'}`);
    } finally {
      try { await reader.disconnect(); appendLog('Déconnexion propre (:cfg_disconnect).'); } catch { /* ignore */ }
      setBusy(false);
    }
  }, [busy, deviceKeyword, smsLogin, smsPassword, nameFilter, format, appendLog]);

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content} testID="ble-dev-scroll">
        <Text style={styles.title}>BLE Private Mode — DEV (lecture seule)</Text>
        <Text style={styles.sub}>
          Phase 1 : connexion GATT au FMC130 et lecture de l'état via « privatemode ? ».
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
        <View style={styles.formatRow}>
          <TouchableOpacity
            style={[styles.formatBtn, format === 'sms_dbg' && styles.formatBtnActive]}
            onPress={() => setFormat('sms_dbg')}
            testID="ble-dev-format-smsdbg"
            accessibilityRole="button"
            accessibilityState={{ selected: format === 'sms_dbg' }}
          >
            <Text style={[styles.formatText, format === 'sms_dbg' && styles.formatTextActive]}>
              @sms_dbg
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.formatBtn, format === 'raw' && styles.formatBtnActive]}
            onPress={() => setFormat('raw')}
            testID="ble-dev-format-raw"
            accessibilityRole="button"
            accessibilityState={{ selected: format === 'raw' }}
          >
            <Text style={[styles.formatText, format === 'raw' && styles.formatTextActive]}>
              privatemode ? (brut)
            </Text>
          </TouchableOpacity>
        </View>

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
          placeholder="Optionnel"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none" autoCorrect={false} testID="ble-dev-login"
          editable={format === 'sms_dbg'}
        />
        <Text style={styles.field}>SMS password — optionnel</Text>
        <TextInput
          style={styles.input} value={smsPassword} onChangeText={setSmsPassword}
          placeholder="Optionnel"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none" autoCorrect={false} secureTextEntry testID="ble-dev-password"
          editable={format === 'sms_dbg'}
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

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  title: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', marginBottom: spacing.xs },
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
  formatRow: { flexDirection: 'row', gap: spacing.sm },
  formatBtn: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingVertical: spacing.sm, alignItems: 'center', backgroundColor: colors.bgCard,
  },
  formatBtnActive: { borderColor: colors.primary, backgroundColor: colors.primary + '22' },
  formatText: { color: colors.textMuted, fontSize: font.size.sm, fontWeight: '600' },
  formatTextActive: { color: colors.primary },
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
