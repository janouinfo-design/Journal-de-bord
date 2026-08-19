import React, { useEffect, useState, useCallback, useMemo } from 'react';
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
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { showConfirm } from '@/utils/alert';
import { colors, spacing, radius, font } from '@/theme/colors';
import { useSessionStore } from '@/store/sessionStore';
import { useQueueStore } from '@/store/queueStore';
import { useAuthStore } from '@/store/authStore';
import { useVehiclesStore } from '@/store/vehiclesStore';
import { useTripsStore } from '@/store/tripsStore';
import { useCurrentSessionPoll } from '@/hooks/useCurrentSession';
import { useQueueFlusher } from '@/hooks/useQueueFlusher';
import { useRealtime } from '@/hooks/useRealtime';
import { bleScanner, ScannerState } from '@/ble/scanner';
import { showLocalNotification } from '@/utils/notifications';
import { Vehicle } from '@/api/ble';
import { deriveRecentVehicles } from '@/utils/recentVehicles';
import type { RootStackParamList } from '@/navigation/RootNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList>;

// Libellé + badge de la source d'identification.
function sourceBadge(source?: string | null): { label: string; auto: boolean } {
  switch (source) {
    case 'BLE':
      return { label: 'BLE', auto: true };
    case 'APP+BLE':
      return { label: 'APP+BLE', auto: true };
    case 'MANUEL':
      return { label: 'MANUEL', auto: false };
    case 'APP':
    default:
      return { label: 'APP', auto: false };
  }
}

// Une session est considérée "auto-identifiée BLE" si la source réelle inclut BLE.
function isAutoBle(source?: string | null): boolean {
  return source === 'BLE' || source === 'APP+BLE';
}

function formatTime(iso?: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString('fr-CH', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
}

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
    blePermissionDenied,
  } = useSessionStore();
  const { size: queueSize, triggerFlush, flushing } = useQueueStore();
  const { user } = useAuthStore();
  const vehiclesStore = useVehiclesStore();
  const tripsStore = useTripsStore();

  const [scannerState, setScannerState] = useState<ScannerState>('idle');
  const [modeSubmitting, setModeSubmitting] = useState<null | 'professional' | 'personal'>(null);
  const [selected, setSelected] = useState<Vehicle | null>(null);

  useCurrentSessionPoll();
  useQueueFlusher();

  // Rafraîchit automatiquement quand une session BLE apparaît/évolue côté serveur.
  useRealtime((event) => {
    if (event.type === 'ble.conflict') {
      showLocalNotification('Conflit détecté', 'Un gestionnaire doit confirmer le conducteur.');
      refresh();
    } else if (event.type === 'kill_switch') {
      showConfirm('Session terminée', event.reason || 'Votre session a été clôturée.');
      refresh();
    } else if (event.type === 'session.update') {
      refresh();
    }
  }, 'driver');

  // Charge flotte (pour recherche/récents) + trajets (pour récents) une fois.
  useEffect(() => {
    vehiclesStore.load();
    tripsStore.load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Scanner BLE (natif). Sur web : reste inactif (indisponible), sans bloquer l'UI.
  useEffect(() => {
    bleScanner.setCallbacks({
      onStateChange: (s) => setScannerState(s),
      onError: () => {},
    });
    bleScanner.start();
    return () => {
      bleScanner.stop();
    };
  }, []);

  const onSetMode = useCallback(
    async (mode: 'professional' | 'personal') => {
      setModeSubmitting(mode);
      const ok = await setMode(mode);
      setModeSubmitting(null);
      if (!ok) showConfirm('Erreur', "Impossible d'enregistrer ce mode. Réessayez.");
    },
    [setMode],
  );

  const onRefresh = useCallback(async () => {
    await refresh();
    await triggerFlush();
    await tripsStore.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, triggerFlush]);

  const onClaim = useCallback(async () => {
    if (!selected) {
      showConfirm('Véhicule requis', 'Sélectionnez d’abord un véhicule.');
      return;
    }
    const res = await claim(selected.id);
    if ('error' in res) {
      showConfirm('Erreur', res.error);
      return;
    }
    if (res.status === 'conflict') {
      showConfirm('Conflit signalé', 'Un gestionnaire doit confirmer le conducteur de ce véhicule.');
    } else {
      setSelected(null);
    }
  }, [selected, claim]);

  const onStop = useCallback(() => {
    showConfirm('Terminer la conduite', 'Confirmez-vous vouloir clôturer votre session en cours ?', [
      { text: 'Annuler', style: 'cancel' },
      {
        text: 'Je m’arrête',
        style: 'destructive',
        onPress: async () => {
          const res = await stop();
          if ('error' in res) {
            showConfirm('Erreur', res.error);
          } else if (res.stopped) {
            showLocalNotification(
              'Conduite terminée',
              `Session clôturée${res.vehicle_plate ? ` · ${res.vehicle_plate}` : ''}.`,
            );
          } else {
            showConfirm('Information', res.message || 'Aucune session active.');
          }
        },
      },
    ]);
  }, [stop]);

  const openPicker = useCallback(() => {
    nav.navigate('VehiclePicker', { onPick: (v: Vehicle) => setSelected(v) });
  }, [nav]);

  const activeMode = session?.mobile_override;
  // Le backend (get_current_session) ne renvoie QUE des sessions ouvertes (OPEN_STATUSES) ;
  // il est la source de vérité. On affiche donc dès qu'une session non fermée existe,
  // qu'elle soit "open" (BLE en cours), "automatic", "confirmed", "manual" ou "pending".
  const hasSession = Boolean(
    session && session.id && session.status !== 'closed',
  );
  const plate = session?.vehicle?.plate ?? null;
  const model = session?.vehicle?.model ?? null;
  const badge = sourceBadge(session?.identification_source);
  const auto = isAutoBle(session?.identification_source);

  // Véhicules récents dérivés des trajets réels du chauffeur.
  const recents = useMemo(
    () => deriveRecentVehicles(tripsStore.trips, vehiclesStore.vehicles, 5),
    [tripsStore.trips, vehiclesStore.vehicles],
  );
  const fleetCount = vehiclesStore.vehicles.length;

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
        </View>

        {/* Bannière conflit (jamais masquée) */}
        {conflict ? (
          <View style={styles.conflictBanner} testID="driver-conflict-banner">
            <Text style={styles.conflictText}>Identification à vérifier</Text>
            <Text style={styles.conflictSub}>
              Plusieurs chauffeurs ont été détectés pour ce véhicule. Un gestionnaire doit confirmer
              le conducteur.
            </Text>
          </View>
        ) : null}

        {hasSession ? (
          /* ============ MODE A — VÉHICULE IDENTIFIÉ ============ */
          <View style={[styles.vehicleCard, styles.vehicleCardActive]} testID="driver-active-card">
            <View style={styles.pulseRow}>
              <View style={styles.pulse} />
              <Text style={styles.pulseLabel}>
                {auto ? '✓ VÉHICULE IDENTIFIÉ AUTOMATIQUEMENT' : 'SESSION ACTIVE'}
              </Text>
            </View>
            <Text style={styles.plate} testID="driver-vehicle-plate">
              {plate ?? '—'}
            </Text>
            <Text style={styles.model}>{model ?? '—'}</Text>

            <View style={styles.sessionMetaRow}>
              <View style={[styles.badge, auto ? styles.badgeAuto : styles.badgeManual]}>
                <Text style={styles.badgeText}>{badge.label}</Text>
              </View>
              <Text style={styles.sessionSince}>Session depuis {formatTime(session?.started_at)}</Text>
            </View>

            {auto ? (
              <Text style={styles.autoHint} testID="driver-auto-hint">
                Identifié automatiquement par votre tag BLE
              </Text>
            ) : (
              <Text style={styles.autoHint}>Identification manuelle</Text>
            )}
          </View>
        ) : (
          /* ============ MODE B — AUCUN VÉHICULE IDENTIFIÉ ============ */
          <View style={styles.vehicleCard}>
            <Text style={styles.noVehicleTitle}>Aucune session active</Text>
            <Text style={styles.noVehicleBody}>
              Nous n'avons pas identifié automatiquement votre véhicule.
            </Text>

            <TouchableOpacity style={styles.searchBtn} onPress={openPicker} testID="driver-open-search">
              <Text style={styles.searchBtnText}>🔎  Rechercher un véhicule</Text>
            </TouchableOpacity>

            {/* Sélection courante */}
            {selected ? (
              <View style={styles.selectedRow} testID="driver-selected-vehicle">
                <Text style={styles.selectedCheck}>✓</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.selectedPlate}>{selected.plate}</Text>
                  {selected.model ? <Text style={styles.selectedModel}>{selected.model}</Text> : null}
                </View>
                <TouchableOpacity onPress={() => setSelected(null)} testID="driver-clear-selection">
                  <Text style={styles.clearSel}>✕</Text>
                </TouchableOpacity>
              </View>
            ) : recents.length > 0 ? (
              <>
                <Text style={styles.sectionLabel}>Véhicules récents</Text>
                {recents.map((v) => (
                  <TouchableOpacity
                    key={v.id}
                    style={styles.recentRow}
                    onPress={() => setSelected(v)}
                    testID={`driver-recent-${v.plate}`}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={styles.recentPlate}>{v.plate}</Text>
                      {v.model ? <Text style={styles.recentModel}>{v.model}</Text> : null}
                    </View>
                    <Text style={styles.chevron}>›</Text>
                  </TouchableOpacity>
                ))}
              </>
            ) : null}

            {/* Voir tous les véhicules */}
            <TouchableOpacity style={styles.seeAll} onPress={openPicker} testID="driver-see-all">
              <Text style={styles.seeAllText}>
                Voir tous les véhicules{fleetCount ? ` (${fleetCount})` : ''}
              </Text>
            </TouchableOpacity>

            {/* Je conduis — actif seulement si un véhicule est sélectionné */}
            <TouchableOpacity
              onPress={onClaim}
              disabled={submitting || !selected}
              style={[styles.claimBtn, (submitting || !selected) && { opacity: 0.5 }]}
              testID="driver-claim-button"
            >
              {submitting ? (
                <ActivityIndicator color={colors.text} />
              ) : (
                <Text style={styles.claimBtnText}>Je conduis</Text>
              )}
            </TouchableOpacity>
          </View>
        )}

        {/* Override PRO/PRIVÉ banner */}
        {activeMode ? (
          <View
            style={[styles.banner, activeMode === 'professional' ? styles.bannerPro : styles.bannerPerso]}
          >
            <Text style={styles.bannerText}>
              Mode {activeMode === 'professional' ? 'PROFESSIONNEL' : 'PRIVÉ'} actif
            </Text>
          </View>
        ) : null}

        {/* PRO / PRIVÉ (indépendant de l'identité chauffeur) */}
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

        {/* Je m'arrête — visible uniquement si session active */}
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

        {/* Statut discret scanner / file offline */}
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
              ⚠ Bluetooth/Permission refusée. Activez le Bluetooth pour la détection automatique.
            </Text>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
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
      return 'permissions…';
    case 'starting':
      return 'démarrage…';
    case 'scanning':
      return 'actif';
    case 'paused':
      return 'en pause';
    case 'error':
      return 'indisponible';
  }
}
function scannerStateColor(s: ScannerState): string {
  if (s === 'scanning') return colors.success;
  if (s === 'error') return colors.textMuted;
  if (s === 'paused' || s === 'idle') return colors.textMuted;
  return colors.warning;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xl, paddingTop: spacing.sm },
  headerRow: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.md },
  helloLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase' },
  helloName: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },

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
  pulse: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.success, marginRight: spacing.sm },
  pulseLabel: { color: colors.success, fontSize: font.size.xs, letterSpacing: 1, fontWeight: '700' },
  plate: { color: colors.text, fontSize: font.size.hero, fontWeight: '700', letterSpacing: 2 },
  model: { color: colors.textMuted, fontSize: font.size.md, marginBottom: spacing.md },
  sessionMetaRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  badge: { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.pill },
  badgeAuto: { backgroundColor: 'rgba(34,197,94,0.18)' },
  badgeManual: { backgroundColor: 'rgba(148,163,184,0.18)' },
  badgeText: { color: colors.text, fontSize: font.size.xs, fontWeight: '700' },
  sessionSince: { color: colors.textMuted, fontSize: font.size.sm },
  autoHint: { color: colors.textMuted, fontSize: font.size.xs, marginTop: spacing.sm },

  noVehicleTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  noVehicleBody: { color: colors.textMuted, fontSize: font.size.sm, marginTop: spacing.xs, lineHeight: 20 },
  searchBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.bg,
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  searchBtnText: { color: colors.primary, fontSize: font.size.md, fontWeight: '600' },
  sectionLabel: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  recentRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  recentPlate: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },
  recentModel: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  chevron: { color: colors.textMuted, fontSize: font.size.lg },
  selectedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderColor: colors.primary,
    backgroundColor: 'rgba(59,130,246,0.12)',
  },
  selectedCheck: { color: colors.primary, fontSize: font.size.lg, fontWeight: '700', marginRight: spacing.sm },
  selectedPlate: { color: colors.text, fontSize: font.size.md, fontWeight: '700' },
  selectedModel: { color: colors.textMuted, fontSize: font.size.xs },
  clearSel: { color: colors.textMuted, fontSize: font.size.lg, paddingHorizontal: spacing.sm },
  seeAll: { marginTop: spacing.md, alignItems: 'center', paddingVertical: spacing.sm },
  seeAllText: { color: colors.primary, fontSize: font.size.sm, fontWeight: '500' },
  claimBtn: {
    marginTop: spacing.md,
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

  modesRow: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.md },
  modeBtn: {
    flex: 1,
    paddingVertical: spacing.lg,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 120,
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
