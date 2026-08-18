import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { showConfirm } from '@/utils/alert';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors, spacing, radius, font } from '@/theme/colors';
import { useSessionStore } from '@/store/sessionStore';
import { useQueueStore } from '@/store/queueStore';
import { useAuthStore } from '@/store/authStore';
import { useCurrentSessionPoll } from '@/hooks/useCurrentSession';
import { useQueueFlusher } from '@/hooks/useQueueFlusher';
import { useRealtime } from '@/hooks/useRealtime';
import { bleScanner, ScannerState } from '@/ble/scanner';
import { showLocalNotification } from '@/utils/notifications';
import { getVehicles, Vehicle } from '@/api/ble';
import type { RootStackParamList } from '@/navigation/RootNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList, 'Driver'>;

// Véhicule sélectionnable pour « Je conduis » (vehicle_id réel).
type SelectableVehicle = { vehicle_id: string; plate: string; model: string | null };

export function DriverScreen() {
  const nav = useNavigation<Nav>();
  const {
    session,
    refresh,
    setMode,
    claim,
    stop,
    submitting,
    conflict,
    bleEnabled,
    blePermissionDenied,
    setBlePermissionDenied,
  } = useSessionStore();
  const { size: queueSize, triggerFlush, flushing } = useQueueStore();
  const { user } = useAuthStore();
  const [scannerState, setScannerState] = useState<ScannerState>('idle');
  const [lastDetection, setLastDetection] = useState<{ id: string; rssi: number } | null>(null);
  const [modeSubmitting, setModeSubmitting] = useState<null | 'professional' | 'personal'>(null);
  const [vehicles, setVehicles] = useState<SelectableVehicle[]>([]);
  const [selectedVehicle, setSelectedVehicle] = useState<string | null>(null);

  useCurrentSessionPoll();
  useQueueFlusher();

  useRealtime((event) => {
    if (event.type === 'ble.conflict') {
      showLocalNotification(
        'Conflit détecté',
        'Un gestionnaire doit confirmer le conducteur.',
      );
      refresh();
    } else if (event.type === 'kill_switch') {
      showConfirm('Session terminée', event.reason || 'Votre session a été clôturée.');
      refresh();
    } else if (event.type === 'session.update') {
      refresh();
    }
  }, 'driver');

  // Charge la liste des véhicules de la flotte (pour « Je conduis »), avec vehicle_id réel.
  const loadVehicles = useCallback(async () => {
    try {
      const list: Vehicle[] = await getVehicles();
      setVehicles(
        list
          .filter((v) => v.id)
          .map((v) => ({ vehicle_id: v.id, plate: v.plate ?? '—', model: v.model })),
      );
    } catch {
      // Pas de blocage : la liste peut être vide (aucune donnée réelle).
      setVehicles([]);
    }
  }, []);

  useEffect(() => {
    loadVehicles();
  }, [loadVehicles]);

  // Start BLE scanner on mount (if enabled).
  useEffect(() => {
    if (!bleEnabled) return;
    bleScanner.setCallbacks({
      onStateChange: (s) => setScannerState(s),
      onDetection: (id, rssi) => setLastDetection({ id, rssi }),
      onError: (msg) => {
        if (msg.toLowerCase().includes('permission')) {
          setBlePermissionDenied(true);
        }
      },
    });
    bleScanner.start();
    return () => {
      bleScanner.stop();
    };
  }, [bleEnabled, setBlePermissionDenied]);

  const onSetMode = useCallback(
    async (mode: 'professional' | 'personal') => {
      setModeSubmitting(mode);
      const ok = await setMode(mode);
      setModeSubmitting(null);
      if (!ok) {
        showConfirm('Erreur', "Impossible d'enregistrer ce mode. Réessayez.");
      }
    },
    [setMode],
  );

  const onRefresh = useCallback(async () => {
    await refresh();
    await triggerFlush();
    await loadVehicles();
  }, [refresh, triggerFlush, loadVehicles]);

  // « Je conduis »
  const onClaim = useCallback(async () => {
    if (!selectedVehicle) {
      showConfirm('Véhicule requis', 'Sélectionnez d’abord un véhicule.');
      return;
    }
    const res = await claim(selectedVehicle);
    if ('error' in res) {
      showConfirm('Erreur', res.error);
      return;
    }
    if (res.status === 'conflict') {
      // La bannière conflit s'affiche déjà ; on informe.
      showConfirm(
        'Conflit signalé',
        'Un gestionnaire doit confirmer le conducteur de ce véhicule.',
      );
    }
  }, [selectedVehicle, claim]);

  // « Je m'arrête » — confirmation + idempotence + anti-double-clic (submitting).
  const onStop = useCallback(() => {
    showConfirm(
      'Terminer la conduite',
      'Confirmez-vous vouloir clôturer votre session en cours ?',
      [
        { text: 'Annuler', style: 'cancel' },
        {
          text: 'Je m’arrête',
          style: 'destructive',
          onPress: async () => {
            const res = await stop();
            if ('error' in res) {
              showConfirm('Erreur', res.error);
              return;
            }
            if (res.stopped) {
              showLocalNotification(
                'Conduite terminée',
                `Session clôturée${res.vehicle_plate ? ` · ${res.vehicle_plate}` : ''}.`,
              );
            } else {
              // Idempotence : session déjà fermée côté serveur (fin auto, timeout…).
              showConfirm('Information', res.message || 'Aucune session active.');
            }
          },
        },
      ],
    );
  }, [stop]);

  const activeMode = session?.mobile_override;
  const hasSession = Boolean(
    session && session.id && session.status !== 'closed' && session.active_driver !== false,
  );
  const plate = session?.vehicle?.plate ?? null;
  const model = session?.vehicle?.model ?? null;
  const sourceLabel = session?.identification_source || 'APP';
  const confidenceLabel =
    session?.confidence == null
      ? 'Confirmé'
      : `${Math.round(session.confidence)} %`;

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl refreshing={flushing} onRefresh={onRefresh} tintColor={colors.text} />
        }
        testID="driver-scroll"
      >
        {/* Header */}
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.helloLabel}>Connecté en tant que</Text>
            <Text style={styles.helloName}>{user?.full_name || user?.email}</Text>
          </View>
          <TouchableOpacity
            onPress={() => nav.navigate('Settings')}
            style={styles.settingsBtn}
            testID="driver-open-settings"
          >
            <Text style={styles.settingsBtnText}>⚙</Text>
          </TouchableOpacity>
        </View>

        {/* Conflict banner (ne PAS masquer) */}
        {conflict ? (
          <View style={styles.conflictBanner} testID="driver-conflict-banner">
            <Text style={styles.conflictText}>Conflit signalé</Text>
            <Text style={styles.conflictSub}>
              Un gestionnaire doit confirmer le conducteur de ce véhicule.
            </Text>
          </View>
        ) : null}

        {/* Vehicle / session card */}
        <View style={[styles.vehicleCard, hasSession ? styles.vehicleCardActive : null]}>
          {hasSession ? (
            <>
              <View style={styles.pulseRow}>
                <View style={styles.pulse} />
                <Text style={styles.pulseLabel}>SESSION ACTIVE · {sourceLabel}</Text>
              </View>
              <Text style={styles.plate} testID="driver-vehicle-plate">
                {plate ?? '—'}
              </Text>
              <Text style={styles.model}>{model ?? '—'}</Text>
              <View style={styles.metricsRow}>
                <Metric
                  label="Début"
                  value={formatTime(session?.started_at)}
                />
                <Metric label="Confiance" value={confidenceLabel} />
                <Metric label="Détections" value={String(session?.detection_count ?? 0)} />
              </View>
            </>
          ) : (
            <>
              <Text style={styles.noVehicleTitle}>Aucune session active</Text>
              <Text style={styles.noVehicleBody}>
                Sélectionnez votre véhicule puis appuyez sur « Je conduis ». Le scan Bluetooth
                (build natif) peut aussi vous identifier automatiquement.
              </Text>
              {lastDetection ? (
                <Text style={styles.detectionHint}>
                  Dernier signal : {lastDetection.id} · {lastDetection.rssi} dBm
                </Text>
              ) : null}
            </>
          )}
        </View>

        {/* Vehicle selector + « Je conduis » (visible sans session active) */}
        {!hasSession ? (
          <View style={styles.claimBlock}>
            <Text style={styles.sectionLabel}>Choisir un véhicule</Text>
            {vehicles.length === 0 ? (
              <Text style={styles.emptyVehicles} testID="driver-no-vehicles">
                Aucun véhicule disponible pour votre flotte (ou données indisponibles).
              </Text>
            ) : (
              <View style={styles.vehicleList}>
                {vehicles.map((v) => (
                  <TouchableOpacity
                    key={v.vehicle_id}
                    style={[
                      styles.vehicleChip,
                      selectedVehicle === v.vehicle_id ? styles.vehicleChipActive : null,
                    ]}
                    onPress={() => setSelectedVehicle(v.vehicle_id)}
                    testID={`driver-vehicle-option-${v.plate}`}
                  >
                    <Text style={styles.vehicleChipPlate}>{v.plate}</Text>
                    {v.model ? <Text style={styles.vehicleChipModel}>{v.model}</Text> : null}
                  </TouchableOpacity>
                ))}
              </View>
            )}
            <TouchableOpacity
              onPress={onClaim}
              disabled={submitting || !selectedVehicle}
              style={[
                styles.claimBtn,
                (submitting || !selectedVehicle) && { opacity: 0.5 },
              ]}
              testID="driver-claim-button"
            >
              {submitting ? (
                <ActivityIndicator color={colors.text} />
              ) : (
                <Text style={styles.claimBtnText}>Je conduis</Text>
              )}
            </TouchableOpacity>
          </View>
        ) : null}

        {/* Override banner */}
        {activeMode ? (
          <View
            style={[
              styles.banner,
              activeMode === 'professional' ? styles.bannerPro : styles.bannerPerso,
            ]}
          >
            <Text style={styles.bannerText}>
              Mode {activeMode === 'professional' ? 'PROFESSIONNEL' : 'PRIVÉ'} actif
            </Text>
            <Text style={styles.bannerSub}>
              Tous les trajets en cours seront classés selon ce mode.
            </Text>
          </View>
        ) : null}

        {/* Mode buttons */}
        <View style={styles.modesRow}>
          <ModeButton
            label="PRO"
            sub="Professionnel"
            color={colors.primary}
            active={activeMode === 'professional'}
            disabled={!hasSession || modeSubmitting !== null}
            loading={modeSubmitting === 'professional'}
            onPress={() => onSetMode('professional')}
            testID="driver-mode-pro"
          />
          <ModeButton
            label="PRIVÉ"
            sub="Personnel"
            color={colors.perso}
            active={activeMode === 'personal'}
            disabled={!hasSession || modeSubmitting !== null}
            loading={modeSubmitting === 'personal'}
            onPress={() => onSetMode('personal')}
            testID="driver-mode-perso"
          />
        </View>

        {/* « Je m'arrête » — visible uniquement si session active */}
        {hasSession ? (
          <TouchableOpacity
            onPress={onStop}
            disabled={submitting}
            style={[styles.stopBtn, submitting && { opacity: 0.6 }]}
            testID="driver-stop-button"
          >
            {submitting ? (
              <ActivityIndicator color={colors.text} />
            ) : (
              <Text style={styles.stopBtnText}>Je m’arrête</Text>
            )}
          </TouchableOpacity>
        ) : null}

        {/* BLE status footer */}
        <View style={styles.footerCard}>
          <Text style={styles.footerLine}>
            <Text style={styles.footerKey}>Scanner BLE : </Text>
            <Text style={{ color: scannerStateColor(scannerState) }}>
              {scannerStateLabel(scannerState)}
            </Text>
          </Text>
          <Text style={styles.footerLine}>
            <Text style={styles.footerKey}>File hors-ligne : </Text>
            {queueSize} détection{queueSize > 1 ? 's' : ''}
          </Text>
          {blePermissionDenied ? (
            <Text style={[styles.footerLine, { color: colors.warning }]}>
              ⚠ Bluetooth/Permission refusée. Activez le Bluetooth et accordez l'accès dans les
              paramètres pour la détection automatique.
            </Text>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function formatTime(iso?: string): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('fr-CH', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricValue}>{value}</Text>
      <Text style={styles.metricLabel}>{label}</Text>
    </View>
  );
}

function ModeButton({
  label,
  sub,
  color,
  active,
  disabled,
  loading,
  onPress,
  testID,
}: {
  label: string;
  sub: string;
  color: string;
  active: boolean;
  disabled: boolean;
  loading: boolean;
  onPress: () => void;
  testID: string;
}) {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled}
      style={[
        styles.modeBtn,
        { backgroundColor: color },
        active ? styles.modeBtnActive : null,
        disabled && !active ? { opacity: 0.5 } : null,
      ]}
      testID={testID}
    >
      <Text style={styles.modeLabel}>{loading ? '…' : label}</Text>
      <Text style={styles.modeSub}>{sub}</Text>
      {active ? <Text style={styles.modeBadge}>ACTIF</Text> : null}
    </TouchableOpacity>
  );
}

function scannerStateLabel(s: ScannerState): string {
  switch (s) {
    case 'idle':
      return 'inactif';
    case 'requesting-permissions':
      return 'demande des permissions';
    case 'starting':
      return 'démarrage…';
    case 'scanning':
      return 'actif';
    case 'paused':
      return 'en pause';
    case 'error':
      return 'erreur';
  }
}

function scannerStateColor(s: ScannerState): string {
  if (s === 'scanning') return colors.success;
  if (s === 'error') return colors.danger;
  if (s === 'paused' || s === 'idle') return colors.textMuted;
  return colors.warning;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xl, paddingTop: spacing.sm },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  helloLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase' },
  helloName: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  settingsBtn: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.pill,
    width: 44,
    height: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  settingsBtnText: { color: colors.text, fontSize: font.size.lg },

  conflictBanner: {
    backgroundColor: 'rgba(245, 158, 11, 0.15)',
    borderColor: colors.warning,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  conflictText: { color: colors.warning, fontWeight: '700', fontSize: font.size.md },
  conflictSub: { color: colors.text, fontSize: font.size.sm, marginTop: 2 },

  vehicleCard: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  vehicleCardActive: { borderColor: colors.primary },
  pulseRow: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.sm },
  pulse: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.success,
    marginRight: spacing.sm,
  },
  pulseLabel: { color: colors.success, fontSize: font.size.xs, letterSpacing: 2, fontWeight: '600' },
  plate: { color: colors.text, fontSize: font.size.hero, fontWeight: '700', letterSpacing: 2 },
  model: { color: colors.textMuted, fontSize: font.size.md, marginBottom: spacing.md },
  metricsRow: { flexDirection: 'row', justifyContent: 'space-between' },
  metric: { flex: 1, alignItems: 'flex-start' },
  metricValue: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  metricLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase' },

  noVehicleTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  noVehicleBody: { color: colors.textMuted, fontSize: font.size.sm, marginTop: spacing.sm, lineHeight: 20 },
  detectionHint: { color: colors.primary, fontSize: font.size.xs, marginTop: spacing.md },

  claimBlock: { marginBottom: spacing.md },
  sectionLabel: {
    color: colors.textMuted,
    fontSize: font.size.sm,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: spacing.sm,
  },
  emptyVehicles: { color: colors.textMuted, fontSize: font.size.sm, marginBottom: spacing.md },
  vehicleList: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md },
  vehicleChip: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  vehicleChipActive: { borderColor: colors.primary, backgroundColor: 'rgba(59,130,246,0.12)' },
  vehicleChipPlate: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },
  vehicleChipModel: { color: colors.textMuted, fontSize: font.size.xs },
  claimBtn: {
    backgroundColor: colors.success,
    paddingVertical: spacing.lg,
    borderRadius: radius.lg,
    alignItems: 'center',
  },
  claimBtnText: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', letterSpacing: 1 },

  banner: { padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md },
  bannerPro: { backgroundColor: 'rgba(59, 130, 246, 0.15)', borderColor: colors.primary, borderWidth: 1 },
  bannerPerso: { backgroundColor: 'rgba(71, 85, 105, 0.15)', borderColor: colors.perso, borderWidth: 1 },
  bannerText: { color: colors.text, fontWeight: '600', fontSize: font.size.md },
  bannerSub: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },

  modesRow: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.md },
  modeBtn: {
    flex: 1,
    paddingVertical: spacing.lg,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 130,
  },
  modeBtnActive: { borderWidth: 3, borderColor: colors.text },
  modeLabel: { color: colors.text, fontSize: font.size.hero, fontWeight: '700', letterSpacing: 2 },
  modeSub: { color: colors.text, fontSize: font.size.sm, opacity: 0.9, marginTop: 4 },
  modeBadge: {
    marginTop: spacing.sm,
    backgroundColor: colors.text,
    color: colors.bg,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    fontSize: font.size.xs,
    fontWeight: '700',
  },

  stopBtn: {
    backgroundColor: colors.danger,
    paddingVertical: spacing.lg,
    borderRadius: radius.lg,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  stopBtnText: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', letterSpacing: 1 },

  footerCard: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  footerLine: { color: colors.text, fontSize: font.size.sm, lineHeight: 22 },
  footerKey: { color: colors.textMuted },
});
