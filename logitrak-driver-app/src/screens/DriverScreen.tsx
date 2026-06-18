import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  RefreshControl,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
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
import type { RootStackParamList } from '@/navigation/RootNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList, 'Driver'>;

export function DriverScreen() {
  const nav = useNavigation<Nav>();
  const { session, refresh, setMode, bleEnabled, blePermissionDenied, setBlePermissionDenied } =
    useSessionStore();
  const { size: queueSize, triggerFlush, flushing } = useQueueStore();
  const { user } = useAuthStore();
  const [scannerState, setScannerState] = useState<ScannerState>('idle');
  const [lastDetection, setLastDetection] = useState<{ id: string; rssi: number } | null>(null);
  const [submitting, setSubmitting] = useState<null | 'professional' | 'personal'>(null);

  useCurrentSessionPoll();
  useQueueFlusher();

  useRealtime((event) => {
    if (event.type === 'ble.conflict') {
      showLocalNotification(
        'Conflit BLE détecté',
        'Plusieurs chauffeurs sur le même véhicule. Choisissez PRO ou PRIVÉ.',
      );
    } else if (event.type === 'kill_switch') {
      Alert.alert('Session terminée', event.reason || 'Votre session a été clôturée.');
      refresh();
    }
  }, 'driver');

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
      setSubmitting(mode);
      const ok = await setMode(mode);
      setSubmitting(null);
      if (!ok) {
        Alert.alert('Erreur', "Impossible d'enregistrer ce mode. Réessayez.");
      }
    },
    [setMode],
  );

  const onRefresh = useCallback(async () => {
    await refresh();
    await triggerFlush();
  }, [refresh, triggerFlush]);

  const activeMode = session?.mobile_override;
  const hasSession = Boolean(session && session.vehicle_id);

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={flushing}
            onRefresh={onRefresh}
            tintColor={colors.text}
          />
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

        {/* Vehicle card */}
        <View style={[styles.vehicleCard, hasSession ? styles.vehicleCardActive : null]}>
          {hasSession ? (
            <>
              <View style={styles.pulseRow}>
                <View style={styles.pulse} />
                <Text style={styles.pulseLabel}>VÉHICULE DÉTECTÉ</Text>
              </View>
              <Text style={styles.plate}>{session?.vehicle_plate ?? '—'}</Text>
              <Text style={styles.model}>{session?.vehicle_model ?? '—'}</Text>
              <View style={styles.metricsRow}>
                <Metric label="RSSI" value={`${session?.rssi_median ?? '–'} dBm`} />
                <Metric label="Détections" value={String(session?.detections_count ?? 0)} />
                <Metric
                  label="Confiance"
                  value={`${Math.round(session?.confidence_score ?? 0)}%`}
                />
              </View>
            </>
          ) : (
            <>
              <Text style={styles.noVehicleTitle}>Recherche en cours…</Text>
              <Text style={styles.noVehicleBody}>
                Approchez-vous d'un véhicule équipé d'un tag Logitrak. Le scan Bluetooth s'effectue
                automatiquement.
              </Text>
              {lastDetection ? (
                <Text style={styles.detectionHint}>
                  Dernier signal : {lastDetection.id} · {lastDetection.rssi} dBm
                </Text>
              ) : null}
            </>
          )}
        </View>

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
            disabled={!hasSession || submitting !== null}
            loading={submitting === 'professional'}
            onPress={() => onSetMode('professional')}
            testID="driver-mode-pro"
          />
          <ModeButton
            label="PRIVÉ"
            sub="Personnel"
            color={colors.perso}
            active={activeMode === 'personal'}
            disabled={!hasSession || submitting !== null}
            loading={submitting === 'personal'}
            onPress={() => onSetMode('personal')}
            testID="driver-mode-perso"
          />
        </View>

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
  pulseLabel: {
    color: colors.success,
    fontSize: font.size.xs,
    letterSpacing: 2,
    fontWeight: '600',
  },
  plate: { color: colors.text, fontSize: font.size.hero, fontWeight: '700', letterSpacing: 2 },
  model: { color: colors.textMuted, fontSize: font.size.md, marginBottom: spacing.md },
  metricsRow: { flexDirection: 'row', justifyContent: 'space-between' },
  metric: { flex: 1, alignItems: 'flex-start' },
  metricValue: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  metricLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase' },

  noVehicleTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  noVehicleBody: { color: colors.textMuted, fontSize: font.size.sm, marginTop: spacing.sm, lineHeight: 20 },
  detectionHint: { color: colors.primary, fontSize: font.size.xs, marginTop: spacing.md },

  banner: {
    padding: spacing.md,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
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
