import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView,
  RefreshControl, ActivityIndicator, Modal, FlatList, AppState,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors, spacing, radius, font } from '@/theme/colors';
import { usePrivateMode } from '@/hooks/usePrivateMode';
import { useKmSummary } from '@/hooks/useKmSummary';
import { useOdometer } from '@/hooks/useOdometer';
import { SegmentedControl } from '@/components/SegmentedControl';
import SosButton from '@/components/SosButton';
import { useTripsStore } from '@/store/tripsStore';
import { countUnclassified, deriveLastTrip } from '@/utils/tripDerivations';
import type { KmPeriod } from '@/api/ble';
import type { Trip } from '@/api/trips';
import type { RootStackParamList } from '@/navigation/RootNavigator';
import {
  getAuthorizedVehicles, Vehicle, SessionVehicle,
} from '@/api/ble';
import { useAssignmentStore, endServiceGate } from '@/store/assignmentStore';

type PickerStatus = 'idle' | 'loading' | 'ready' | 'error';
type Nav = NativeStackNavigationProp<RootStackParamList>;

const PERIOD_OPTIONS: { value: KmPeriod; label: string }[] = [
  { value: 'today', label: "Aujourd'hui" },
  { value: 'week', label: 'Semaine' },
  { value: 'month', label: 'Mois' },
];

const fmtKm = (v: number | null | undefined) =>
  (typeof v === 'number' ? `${v.toFixed(1)} km` : '—');

const fmtInt = (v: number | null | undefined) =>
  (typeof v === 'number' ? `${Math.round(v).toLocaleString('fr-CH')} km` : '—');

function fmtTime(iso?: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString('fr-CH', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

/**
 * Écran chauffeur — MODE MANUEL (sans Bluetooth) — refonte premium (dark).
 * Ordre : Véhicule actuel -> Mode PRO/PRIVÉ -> Kilomètres (segmented) -> Total ->
 *         Trajets à classifier (conditionnel) -> Dernier trajet -> Odomètre/Confidentialité -> SOS.
 * Backend = seule source de vérité (session, PRO/PRIVÉ, km, odomètre). Aucune donnée inventée.
 * Aucun jargon technique (pas de BLE/AVL/Navixy/Teltonika/tracker).
 */
export default function DriverScreenManual() {
  const nav = useNavigation<Nav>();
  const [vehicle, setVehicle] = useState<SessionVehicle | null>(null);
  const [connected, setConnected] = useState<boolean>(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [myVehicles, setMyVehicles] = useState<Vehicle[]>([]);
  const [pickerStatus, setPickerStatus] = useState<PickerStatus>('idle');
  const [defaultVehicleId, setDefaultVehicleId] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [pendingChange, setPendingChange] = useState<Vehicle | null>(null);  // confirmation CHANGE A->B
  const [refreshing, setRefreshing] = useState(false);
  const [period, setPeriod] = useState<KmPeriod>('today');

  const privateMode = usePrivateMode();
  // Source de vérité du VÉHICULE ACTIF = affectation persistante (Lot 2 backend).
  // Sélecteurs STABLES (évite les re-render/boucles : on ne prend pas l'objet store entier).
  const assignment = useAssignmentStore((s) => s.assignment);
  const asgUxState = useAssignmentStore((s) => s.uxState);
  const asgOffline = useAssignmentStore((s) => s.offline);
  const asgInFlight = useAssignmentStore((s) => s.inFlight);
  const asgActionError = useAssignmentStore((s) => s.actionError);
  const asgRefresh = useAssignmentStore((s) => s.refresh);
  const asgTake = useAssignmentStore((s) => s.take);
  const asgChange = useAssignmentStore((s) => s.change);
  const asgEnd = useAssignmentStore((s) => s.end);
  // Véhicule dérivé de l'affectation (pour km/odomètre qui ont besoin d'un vehicle.id).
  const vehicleFromAssignment: SessionVehicle | null = assignment
    ? { id: assignment.vehicle_id, plate: assignment.vehicle_plate || null, model: assignment.vehicle_model || null }
    : null;
  const km = useKmSummary(vehicleFromAssignment?.id, period);
  const odo = useOdometer(vehicleFromAssignment?.id);
  const tripsStore = useTripsStore();

  useEffect(() => {
    tripsStore.load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadAuthorized = useCallback(async (): Promise<Vehicle[]> => {
    setPickerStatus('loading');
    try {
      const r = await getAuthorizedVehicles();
      setMyVehicles(r.vehicles);
      setDefaultVehicleId(r.default_vehicle_id);
      setPickerStatus('ready');
      return r.vehicles;
    } catch {
      setMyVehicles([]);
      setPickerStatus('error');
      return [];
    }
  }, []);

  const loadVehicle = useCallback(async () => {
    // Source de vérité = affectation persistante. Le store gère loading/ready/error/offline.
    await asgRefresh();
  }, [asgRefresh]);

  // Synchronise l'état local `vehicle` (rétro-compat km/odo) avec l'affectation.
  useEffect(() => {
    if (assignment) {
      setVehicle({
        id: assignment.vehicle_id,
        plate: assignment.vehicle_plate || null,
        model: assignment.vehicle_model || null,
      } as SessionVehicle);
      setConnected(!asgOffline);
    } else {
      setVehicle(null);
      setConnected(false);
    }
  }, [assignment, asgOffline]);

  // BOOT : charge l'affectation UNE fois au montage (asgRefresh est une action zustand STABLE).
  useEffect(() => {
    asgRefresh();
    loadAuthorized();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Retour au premier plan -> re-lecture de l'affectation réelle (jamais d'état obsolète).
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (next === 'active') asgRefresh();
    });
    return () => sub.remove();
  }, [asgRefresh]);

  const openPicker = useCallback(async () => {
    setPickerOpen(true);
    await loadAuthorized();
  }, [loadAuthorized]);

  const selectVehicle = useCallback(async (v: Vehicle) => {
    if (switching) return;
    // Si un véhicule est déjà actif et qu'on en choisit un AUTRE -> CHANGE avec confirmation.
    if (assignment && v.id !== assignment.vehicle_id) {
      setPendingChange(v);          // ouvre la confirmation A -> B
      return;
    }
    // Idempotent : re-sélection du véhicule actuel -> no-op côté UX
    if (assignment && v.id === assignment.vehicle_id) {
      setPickerOpen(false);
      return;
    }
    // Aucun véhicule actif -> TAKE direct
    setSwitching(true);
    try {
      const res = await asgTake(v.id);
      if (res && res.result === 'ok') {
        setPickerOpen(false);
        await privateMode.refresh();
      }
    } finally {
      setSwitching(false);
    }
  }, [switching, assignment, asgTake, privateMode]);

  // Confirmation du changement A -> B (jamais deux ACTIVE ; A reste si B occupé).
  const confirmChange = useCallback(async () => {
    if (!pendingChange || switching) return;
    const target = pendingChange;
    setSwitching(true);
    try {
      const res = await asgChange(target.id);
      setPendingChange(null);
      if (res && res.result === 'ok') {
        setPickerOpen(false);
        await privateMode.refresh();
      }
      // conflit -> asgActionError affiché ; A reste ACTIVE (backend garanti)
    } finally {
      setSwitching(false);
    }
  }, [pendingChange, switching, asgChange, privateMode]);

  // « Fin de service » — autorisée UNIQUEMENT si Mode Privé = BUSINESS CONFIRMÉ (fail-closed).
  const endGate = endServiceGate(privateMode.status, false);
  const endService = useCallback(async () => {
    if (!endGate.allowed) return;               // garde-fou : bouton bloqué si mode != BUSINESS
    const res = await asgEnd();
    if (res && res.result === 'ok') {
      await privateMode.refresh();
    }
  }, [endGate.allowed, asgEnd, privateMode]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([
      asgRefresh(), loadAuthorized(), privateMode.refresh(),
      km.refresh(), odo.refresh(), tripsStore.refresh(),
    ]);
    setRefreshing(false);
  }, [asgRefresh, loadAuthorized, privateMode, km, odo, tripsStore]);

  const highlightId = vehicle?.id
    ?? (defaultVehicleId && myVehicles.some((v) => v.id === defaultVehicleId)
        ? defaultVehicleId
        : null);

  const st = privateMode.status.state;
  const isPrivate = st === 'PRIVATE';
  const isBusiness = st === 'BUSINESS';
  const isPending = st === 'PENDING_CONFIRMATION' || st === 'PRIVATE_REQUESTED' || st === 'BUSINESS_REQUESTED';
  const hasVehicle = !!assignment;
  const canToggle = hasVehicle && privateMode.status.allowed && !privateMode.busy;

  // Total + répartition Pro/Privé (jamais de division par zéro ; jamais de valeur inventée).
  const proKm = km.proKm;
  const privKm = km.privateKm;
  const hasKm = typeof proKm === 'number' && typeof privKm === 'number';
  const total = hasKm ? proKm! + privKm! : null;
  const proPct = hasKm && total! > 0 ? Math.round((proKm! / total!) * 100) : 0;
  const privPct = hasKm && total! > 0 ? 100 - proPct : 0;

  // Trajets réels : dernier trajet + nombre à classifier (données réelles uniquement).
  const trips = tripsStore.trips;
  const unclassified = useMemo(() => countUnclassified(trips), [trips]);
  const lastTrip = useMemo(() => deriveLastTrip(trips), [trips]);

  const openTripDetail = useCallback((t: Trip) => {
    nav.navigate('TripDetail', { tripId: t.id });
  }, [nav]);

  const openTripsTab = useCallback(() => {
    // Onglet "Trajets" (bottom nav). Le filtre non-classifié y est géré si présent.
    (nav as any).navigate('Main', { screen: 'Trajets' });
  }, [nav]);

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
        testID="conduite-scroll"
      >
        <Text style={styles.screenTitle} accessibilityRole="header">Conduite</Text>

        {/* ============ MON VÉHICULE — états UX EXCLUSIFS (jamais deux à la fois) ============ */}
        <Text style={styles.sectionLabel}>Mon véhicule</Text>
        <View style={styles.vehicleCard} testID="manual-vehicle-card">
          {asgUxState === 'loading' ? (
            /* LOADING : uniquement le spinner + texte. AUCUN bouton "Choisir". */
            <View style={styles.centerBox} testID="manual-vehicle-loading">
              <ActivityIndicator color={colors.primary} />
              <Text style={styles.loadingText}>Chargement de votre véhicule…</Text>
            </View>
          ) : asgUxState === 'error' ? (
            /* ERROR : erreur réseau/API != aucun véhicule. Réessayer. */
            <View testID="manual-vehicle-error">
              <Text style={styles.emptyText}>Impossible de vérifier votre véhicule.</Text>
              <TouchableOpacity style={styles.changeBtn} onPress={loadVehicle} testID="manual-vehicle-retry">
                <Text style={styles.changeBtnText}>Réessayer</Text>
              </TouchableOpacity>
            </View>
          ) : hasVehicle ? (
            /* ACTIVE (ou OFFLINE avec cache) : véhicule + En service depuis + actions. */
            <>
              <View style={styles.vehicleRowTop}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.vehiclePlate} testID="manual-vehicle-plate">
                    {assignment?.vehicle_plate || assignment?.vehicle_label || 'Véhicule'}
                  </Text>
                  {assignment?.vehicle_model ? (
                    <Text style={styles.vehicleModel}>{assignment.vehicle_model}</Text>
                  ) : null}
                  {assignment?.segment_started_at ? (
                    <Text style={styles.vehicleModel} testID="manual-since">
                      En service depuis {fmtTime(assignment.segment_started_at)}
                    </Text>
                  ) : null}
                </View>
                <View
                  style={[styles.connPill, { backgroundColor: asgOffline ? colors.persoSoft : colors.successSoft }]}
                  accessibilityLabel={asgOffline ? 'Mode hors ligne' : 'En service'}
                >
                  <View style={[styles.dot, { backgroundColor: asgOffline ? colors.textMuted : colors.success }]} />
                  <Text style={[styles.connText, { color: asgOffline ? colors.textMuted : colors.success }]}>
                    {asgOffline ? 'Hors ligne' : 'En service'}
                  </Text>
                </View>
              </View>

              {/* Changer de véhicule (bloqué hors ligne). */}
              <TouchableOpacity
                style={styles.changeBtn}
                onPress={openPicker}
                disabled={asgOffline}
                testID="manual-change-vehicle"
                accessibilityRole="button"
                accessibilityLabel="Changer de véhicule"
              >
                <Text style={styles.changeBtnText}>Changer de véhicule</Text>
              </TouchableOpacity>

              {/* Fin de service : TOUJOURS visible si véhicule actif ; action gated par endGate. */}
              <TouchableOpacity
                style={[styles.endBtn, !endGate.allowed && styles.endBtnDisabled]}
                onPress={endService}
                disabled={!endGate.allowed || asgInFlight || asgOffline}
                testID="manual-end-service"
                accessibilityRole="button"
                accessibilityLabel="Fin de service"
              >
                <Text style={[styles.endBtnText, !endGate.allowed && styles.endBtnTextDisabled]}>
                  Fin de service
                </Text>
              </TouchableOpacity>
              {!endGate.allowed && endGate.message ? (
                <Text style={styles.endHint} testID="manual-end-hint">{endGate.message}</Text>
              ) : null}
              {asgActionError ? (
                <Text style={styles.endHint} testID="manual-assignment-error">{asgActionError}</Text>
              ) : null}
            </>
          ) : (
            /* NONE : aucun véhicule actif -> proposer Choisir. */
            <View testID="manual-no-vehicle">
              <Text style={styles.emptyText}>Aucun véhicule en cours</Text>
              <TouchableOpacity
                style={styles.changeBtn}
                onPress={openPicker}
                testID="manual-choose-vehicle"
                accessibilityRole="button"
                accessibilityLabel="Choisir un véhicule"
              >
                <Text style={styles.changeBtnText}>Choisir un véhicule</Text>
              </TouchableOpacity>
              {asgActionError ? (
                <Text style={styles.endHint} testID="manual-assignment-error">{asgActionError}</Text>
              ) : null}
            </View>
          )}
        </View>

        {/* ============ MODE ============ */}
        <Text style={styles.sectionLabel}>Mode</Text>
        <View style={styles.modesRow}>
          <ModeCard
            label="Professionnel"
            active={isBusiness}
            disabled={!canToggle || isBusiness}
            loading={isPending && !isPrivate}
            color={colors.pro}
            onPress={() => privateMode.requestMode('BUSINESS')}
            testID="manual-mode-pro"
          />
          <ModeCard
            label="Privé"
            active={isPrivate}
            disabled={!canToggle || isPrivate}
            loading={isPending && !isBusiness}
            color={colors.perso}
            onPress={() => privateMode.requestMode('PRIVATE')}
            testID="manual-mode-private"
          />
        </View>

        {hasVehicle && privateMode.status.allowed ? (
          <Text style={styles.helpText} testID="manual-mode-help">
            {isPrivate
              ? (privateMode.privateOdometerSupported
                  ? 'Mode Privé actif. La position du véhicule est masquée. Vos kilomètres privés restent comptabilisés.'
                  : 'Mode Privé actif. La position du véhicule est masquée.')
              : isBusiness
              ? 'Mode Professionnel actif. Les nouveaux trajets seront enregistrés comme professionnels.'
              : isPending
              ? (privateMode.sentMessage || privateMode.status.pending_message || 'Commande envoyée.')
              : 'Sélectionnez votre mode.'}
          </Text>
        ) : null}

        {privateMode.error ? (
          <Text style={styles.errorText} testID="manual-mode-error">{privateMode.error}</Text>
        ) : null}
        {privateMode.timedOut && !isPending ? (
          <Text style={styles.errorText} testID="manual-mode-timeout">
            Commande envoyée mais état non confirmé. Vérifiez l’état du véhicule.
          </Text>
        ) : null}

        {/* ============ KILOMÈTRES ============ */}
        <Text style={styles.sectionLabel}>Kilomètres</Text>
        <SegmentedControl
          options={PERIOD_OPTIONS}
          value={period}
          onChange={setPeriod}
          testID="km-period"
        />
        {km.periodLabel ? (
          <Text style={styles.periodCaption} testID="km-period-label">{km.periodLabel}</Text>
        ) : null}

        <View style={styles.kmRow}>
          <View style={styles.kmCard} testID="manual-km-pro">
            <Text style={styles.kmTitle}>Km Pro</Text>
            <Text style={[styles.kmValue, { color: colors.pro }]} testID="manual-km-pro-value">
              {km.loading ? '…' : fmtKm(proKm)}
            </Text>
          </View>
          <View style={styles.kmCard} testID="manual-km-private">
            <Text style={styles.kmTitle}>Km Privé</Text>
            <Text style={[styles.kmValue, { color: colors.text }]} testID="manual-km-private-value">
              {km.loading ? '…' : fmtKm(privKm)}
            </Text>
          </View>
        </View>

        {/* ============ TOTAL + RÉPARTITION ============ */}
        <View style={styles.totalCard} testID="manual-km-total">
          <View style={styles.totalHeader}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalValue} testID="manual-km-total-value">
              {km.loading ? '…' : fmtKm(total)}
            </Text>
          </View>
          <View style={styles.ratioRow}>
            <Text style={styles.ratioText}>Pro {proPct} %</Text>
            <Text style={styles.ratioText}>Privé {privPct} %</Text>
          </View>
          <View style={styles.bar} accessibilityLabel={`Répartition Pro ${proPct}%, Privé ${privPct}%`}>
            <View style={[styles.barPro, { flex: proPct }]} />
            <View style={[styles.barPriv, { flex: privPct }]} />
            {proPct === 0 && privPct === 0 ? <View style={styles.barEmpty} /> : null}
          </View>
        </View>

        {/* ============ TRAJETS À CLASSIFIER (conditionnel) ============ */}
        {unclassified > 0 ? (
          <TouchableOpacity
            style={styles.warnCard}
            onPress={openTripsTab}
            testID="manual-unclassified"
            accessibilityRole="button"
            accessibilityLabel={`${unclassified} trajets à classifier`}
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.warnTitle}>⚠ {unclassified} trajet{unclassified > 1 ? 's' : ''} à classifier</Text>
              <Text style={styles.warnSub}>Merci de vérifier vos trajets non classifiés.</Text>
            </View>
            <Text style={styles.chevron}>›</Text>
          </TouchableOpacity>
        ) : null}

        {/* ============ DERNIER TRAJET ============ */}
        <Text style={styles.sectionLabel}>Dernier trajet</Text>
        {lastTrip ? (
          <TouchableOpacity
            style={styles.tripCard}
            onPress={() => openTripDetail(lastTrip)}
            testID="manual-last-trip"
            accessibilityRole="button"
            accessibilityLabel="Voir le détail du dernier trajet"
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.tripRoute} numberOfLines={1}>
                {(lastTrip.start_address || 'Départ')} → {(lastTrip.end_address || 'Arrivée')}
              </Text>
              <Text style={styles.tripMeta}>
                {fmtKm(lastTrip.distance_km)}
                {lastTrip.classification
                  ? ` · ${lastTrip.classification === 'professional' ? 'Professionnel' : 'Privé'}`
                  : ' · Non classé'}
                {fmtTime(lastTrip.start_time) ? ` · ${fmtTime(lastTrip.start_time)}` : ''}
                {fmtTime(lastTrip.end_time) ? ` – ${fmtTime(lastTrip.end_time)}` : ''}
              </Text>
            </View>
            <Text style={styles.chevron}>›</Text>
          </TouchableOpacity>
        ) : (
          <View style={styles.emptyCard} testID="manual-last-trip-empty">
            <Text style={styles.emptyText}>Aucun trajet enregistré pour le moment.</Text>
          </View>
        )}

        {/* ============ ODOMÈTRE + CONFIDENTIALITÉ ============ */}
        <View style={styles.dualRow}>
          <View style={styles.infoCard} testID="manual-odometer">
            <Text style={styles.infoTitle}>Odomètre véhicule</Text>
            <Text style={styles.infoValue} testID="manual-odometer-value">
              {odo.loading ? '…' : fmtInt(odo.odometerKm)}
            </Text>
            {!odo.loading && !odo.available ? (
              <Text style={styles.infoSub}>Donnée indisponible</Text>
            ) : null}
          </View>
          <View style={styles.infoCard} testID="manual-privacy">
            <Text style={styles.infoTitle}>{isPrivate ? 'Position masquée' : 'Position visible'}</Text>
            <Text style={[styles.infoBadge, { color: isPrivate ? colors.perso : colors.primary }]}>
              {isPrivate ? 'Mode privé' : 'Mode professionnel'}
            </Text>
          </View>
        </View>

        {/* ============ SOS ============ */}
        <SosButton isPrivate={isPrivate} />
      </ScrollView>

      {/* ============ Modal : Choisir un véhicule ============ */}
      <Modal visible={pickerOpen} animationType="slide" transparent onRequestClose={() => setPickerOpen(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Choisir un véhicule</Text>
              <TouchableOpacity onPress={() => setPickerOpen(false)} testID="manual-picker-close">
                <Text style={styles.modalClose}>Fermer</Text>
              </TouchableOpacity>
            </View>
            {pickerStatus === 'loading' ? (
              <ActivityIndicator style={{ marginVertical: spacing.lg }} color={colors.primary} testID="manual-picker-loading" />
            ) : pickerStatus === 'error' ? (
              <View testID="manual-picker-error">
                <Text style={styles.errorText}>Impossible de charger la liste des véhicules.</Text>
                <TouchableOpacity style={styles.retryBtn} onPress={() => loadAuthorized()} testID="manual-picker-retry">
                  <Text style={styles.retryBtnText}>Réessayer</Text>
                </TouchableOpacity>
              </View>
            ) : myVehicles.length === 0 ? (
              <Text style={styles.emptyText} testID="manual-picker-empty">
                Aucun véhicule autorisé. Contactez votre gestionnaire.
              </Text>
            ) : (
              <FlatList
                data={myVehicles}
                keyExtractor={(v) => v.id}
                renderItem={({ item }) => {
                  const isActive = item.id === vehicle?.id;
                  const isDefault = !isActive && item.id === highlightId;
                  return (
                    <TouchableOpacity
                      style={[styles.pickerRow, (isActive || isDefault) && styles.pickerRowSelected]}
                      onPress={() => selectVehicle(item)}
                      disabled={switching}
                      testID={`manual-picker-item-${item.id}`}
                    >
                      <View style={{ flex: 1 }}>
                        <Text style={styles.rowPlate}>{item.plate || item.label || 'Véhicule'}</Text>
                        {item.model ? <Text style={styles.rowModel}>{item.model}</Text> : null}
                      </View>
                      {isActive ? <Text style={styles.rowCurrent}>Actuel</Text> : null}
                      {isDefault ? <Text style={styles.rowCurrent}>Par défaut</Text> : null}
                    </TouchableOpacity>
                  );
                }}
              />
            )}
            {switching ? <ActivityIndicator style={{ marginTop: spacing.md }} color={colors.primary} /> : null}
          </View>
        </View>
      </Modal>

      {/* ============ Confirmation : Changer de véhicule (A -> B) ============ */}
      <Modal visible={!!pendingChange} animationType="fade" transparent onRequestClose={() => setPendingChange(null)}>
        <View style={styles.confirmOverlay}>
          <View style={styles.confirmCard} testID="manual-change-confirm">
            <Text style={styles.confirmTitle}>Changer de véhicule ?</Text>
            <Text style={styles.confirmBody}>
              {(assignment?.vehicle_plate || 'Véhicule actuel')}  →  {(pendingChange?.plate || pendingChange?.label || 'Nouveau véhicule')}
            </Text>
            <View style={styles.confirmRow}>
              <TouchableOpacity
                style={[styles.confirmBtn, styles.confirmCancel]}
                onPress={() => setPendingChange(null)}
                disabled={switching}
                testID="manual-change-cancel"
              >
                <Text style={styles.confirmCancelText}>Annuler</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.confirmBtn, styles.confirmOk]}
                onPress={confirmChange}
                disabled={switching}
                testID="manual-change-ok"
              >
                <Text style={styles.confirmOkText}>{switching ? 'Changement…' : 'Confirmer'}</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function ModeCard({ label, active, disabled, loading, color, onPress, testID }: {
  label: string; active: boolean; disabled: boolean; loading: boolean;
  color: string; onPress: () => void; testID: string;
}) {
  return (
    <TouchableOpacity
      style={[styles.modeCard, active && { borderColor: color, backgroundColor: color + '22' }, disabled && styles.modeCardDisabled]}
      onPress={onPress}
      disabled={disabled}
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ selected: active, disabled }}
      accessibilityLabel={`${label} — ${active ? 'actif' : 'activer'}`}
    >
      <Text style={[styles.modeLabel, active && { color }]}>{label}</Text>
      {loading ? <ActivityIndicator size="small" color={color} /> : (
        <Text style={[styles.modeState, active && { color }]}>{active ? 'Actif' : 'Activer'}</Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  content: { paddingHorizontal: spacing.md, paddingTop: spacing.xs, paddingBottom: spacing.xxl },
  screenTitle: {
    color: colors.text, fontSize: font.size.xxl, fontWeight: '700',
    marginBottom: spacing.xs, marginTop: 0,
  },
  sectionLabel: {
    color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase',
    letterSpacing: 1, marginBottom: spacing.sm, marginTop: spacing.lg,
  },

  vehicleCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg,
  },
  vehicleRowTop: { flexDirection: 'row', alignItems: 'flex-start' },
  vehiclePlate: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', letterSpacing: 1 },
  vehicleModel: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  connPill: {
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: spacing.sm,
    paddingVertical: 4, borderRadius: radius.pill,
  },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  connText: { fontSize: font.size.xs, fontWeight: '700' },
  emptyText: { color: colors.textMuted, fontSize: font.size.md, paddingVertical: spacing.md },
  centerBox: { alignItems: 'center', paddingVertical: spacing.lg, gap: spacing.sm },
  loadingText: { color: colors.textMuted, fontSize: font.size.md },
  changeBtn: {
    marginTop: spacing.md, backgroundColor: colors.primary, borderRadius: radius.md,
    paddingVertical: spacing.md, alignItems: 'center',
  },
  changeBtnText: { color: colors.textInverse, fontSize: font.size.md, fontWeight: '700' },

  // Fin de service : action distincte (secondaire, contour), bloquée si mode != BUSINESS.
  endBtn: {
    marginTop: spacing.sm, borderRadius: radius.md, paddingVertical: spacing.md,
    alignItems: 'center', borderWidth: 1, borderColor: colors.perso, backgroundColor: 'transparent',
  },
  endBtnDisabled: { borderColor: colors.border, opacity: 0.6 },
  endBtnText: { color: colors.perso, fontSize: font.size.md, fontWeight: '700' },
  endBtnTextDisabled: { color: colors.textMuted },
  endHint: { color: colors.textMuted, fontSize: font.size.sm, marginTop: spacing.xs },

  // Confirmation CHANGE A->B
  confirmOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.45)', justifyContent: 'center', padding: spacing.lg },
  confirmCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, padding: spacing.lg },
  confirmTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', marginBottom: spacing.sm },
  confirmBody: { color: colors.text, fontSize: font.size.md, marginBottom: spacing.lg },
  confirmRow: { flexDirection: 'row', gap: spacing.md },
  confirmBtn: { flex: 1, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: 'center' },
  confirmCancel: { backgroundColor: 'transparent', borderWidth: 1, borderColor: colors.border },
  confirmCancelText: { color: colors.text, fontWeight: '700' },
  confirmOk: { backgroundColor: colors.primary },
  confirmOkText: { color: colors.textInverse, fontWeight: '700' },

  modesRow: { flexDirection: 'row', gap: spacing.md },
  modeCard: {
    flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 2,
    borderColor: colors.border, paddingVertical: spacing.xl, alignItems: 'center',
  },
  modeCardDisabled: { opacity: 0.55 },
  modeLabel: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', marginBottom: 6 },
  modeState: { color: colors.textMuted, fontSize: font.size.sm, fontWeight: '600' },
  helpText: { color: colors.textMuted, fontSize: font.size.sm, marginTop: spacing.md, lineHeight: 20 },
  errorText: { color: colors.danger, fontSize: font.size.sm, marginTop: spacing.sm },

  periodCaption: {
    color: colors.textMuted, fontSize: font.size.xs, marginTop: spacing.sm, marginLeft: 2,
  },
  kmRow: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.md },
  kmCard: {
    flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, alignItems: 'flex-start',
  },
  kmTitle: { color: colors.textMuted, fontSize: font.size.sm, fontWeight: '600', marginBottom: spacing.sm },
  kmValue: { fontSize: font.size.xl, fontWeight: '700' },

  totalCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, marginTop: spacing.md,
  },
  totalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  totalLabel: { color: colors.textMuted, fontSize: font.size.sm, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1 },
  totalValue: { color: colors.text, fontSize: font.size.xl, fontWeight: '700' },
  ratioRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: spacing.md, marginBottom: spacing.sm },
  ratioText: { color: colors.textMuted, fontSize: font.size.sm, fontWeight: '600' },
  bar: {
    flexDirection: 'row', height: 10, borderRadius: radius.pill, overflow: 'hidden',
    backgroundColor: colors.bg,
  },
  barPro: { backgroundColor: colors.pro },
  barPriv: { backgroundColor: colors.perso },
  barEmpty: { position: 'absolute', left: 0, right: 0, top: 0, bottom: 0, backgroundColor: colors.bg },

  warnCard: {
    flexDirection: 'row', alignItems: 'center', marginTop: spacing.md,
    backgroundColor: colors.warningSoft, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.warningBorder, padding: spacing.md,
  },
  warnTitle: { color: colors.warning, fontSize: font.size.md, fontWeight: '700' },
  warnSub: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },

  tripCard: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg,
  },
  tripRoute: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },
  tripMeta: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 4 },
  emptyCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg,
  },
  chevron: { color: colors.textMuted, fontSize: font.size.xl, marginLeft: spacing.sm },

  dualRow: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.lg },
  infoCard: {
    flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg,
  },
  infoTitle: { color: colors.textMuted, fontSize: font.size.sm, fontWeight: '600' },
  infoValue: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', marginTop: spacing.sm },
  infoSub: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  infoBadge: { fontSize: font.size.md, fontWeight: '700', marginTop: spacing.sm },

  modalBackdrop: { flex: 1, backgroundColor: colors.overlay, justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: colors.bg, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    padding: spacing.lg, maxHeight: '75%',
  },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.md },
  modalTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '700' },
  modalClose: { color: colors.primary, fontSize: font.size.md },
  pickerRow: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.sm,
  },
  pickerRowSelected: { borderColor: colors.primary },
  retryBtn: {
    marginTop: spacing.md, alignSelf: 'flex-start', borderWidth: 1, borderColor: colors.primary,
    borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  retryBtnText: { color: colors.primary, fontWeight: '600', fontSize: font.size.md },
  rowPlate: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },
  rowModel: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  rowCurrent: { color: colors.primary, fontSize: font.size.xs, fontWeight: '600' },
});
