import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView,
  RefreshControl, ActivityIndicator, Modal, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, radius, font } from '@/theme/colors';
import { usePrivateMode } from '@/hooks/usePrivateMode';
import { useKmSummary } from '@/hooks/useKmSummary';
import SosButton from '@/components/SosButton';
import {
  getAuthorizedVehicles, claimVehicle, getMyVehicle, Vehicle, SessionVehicle,
} from '@/api/ble';

type PickerStatus = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Écran chauffeur — MODE MANUEL (sans Bluetooth).
 * Hiérarchie : Véhicule actuel -> Changer de véhicule -> PRO/PRIVÉ -> Km Pro/Privé.
 * Backend = seule source de vérité (session, PRO/PRIVÉ, km). Aucun calcul GPS mobile.
 * Aucun jargon technique (pas de BLE/AVL/Navixy/Teltonika/tracker).
 */
export default function DriverScreenManual() {
  const [vehicle, setVehicle] = useState<SessionVehicle | null>(null);
  const [connected, setConnected] = useState<boolean>(false);
  const [loadingVehicle, setLoadingVehicle] = useState(true);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [myVehicles, setMyVehicles] = useState<Vehicle[]>([]);
  const [pickerStatus, setPickerStatus] = useState<PickerStatus>('idle');
  const [defaultVehicleId, setDefaultVehicleId] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Empêche de rouvrir automatiquement le picker en boucle (une seule proposition).
  const autoOpenedRef = useRef(false);

  const privateMode = usePrivateMode();
  const km = useKmSummary(vehicle?.id, 'today');

  // Charge les véhicules AUTORISÉS (périmètre strict backend). Distingue ERROR / EMPTY.
  const loadAuthorized = useCallback(async (): Promise<Vehicle[]> => {
    setPickerStatus('loading');
    try {
      const r = await getAuthorizedVehicles();
      setMyVehicles(r.vehicles);
      setDefaultVehicleId(r.default_vehicle_id);
      setPickerStatus('ready');
      return r.vehicles;
    } catch {
      // Erreur réseau/serveur : NE JAMAIS présenter comme "aucun véhicule".
      setMyVehicles([]);
      setPickerStatus('error');
      return [];
    }
  }, []);

  const loadVehicle = useCallback(async () => {
    setLoadingVehicle(true);
    try {
      const r = await getMyVehicle();
      if (r?.vehicle?.id) {
        setVehicle(r.vehicle);
        setConnected(!!r.current);
      } else {
        setVehicle(null);
        setConnected(false);
      }
    } catch {
      setVehicle(null);
      setConnected(false);
    } finally {
      setLoadingVehicle(false);
    }
  }, []);

  // Au montage : lit la session courante (restauration) PUIS le périmètre autorisé.
  // Si aucun véhicule actif : proposition = default_vehicle_id (uniquement s'il est
  // AUTORISÉ), jamais le premier véhicule arbitrairement. Ouvre le picker une fois.
  useEffect(() => {
    (async () => {
      await loadVehicle();
      await loadAuthorized();
    })();
  }, [loadVehicle, loadAuthorized]);

  // Auto-ouverture du picker si, après chargement, aucun véhicule n'est actif et que
  // le périmètre autorisé est disponible et non vide (une seule fois).
  useEffect(() => {
    if (autoOpenedRef.current) return;
    if (loadingVehicle || pickerStatus !== 'ready') return;
    if (!vehicle?.id && myVehicles.length > 0) {
      autoOpenedRef.current = true;
      setPickerOpen(true);
    }
  }, [loadingVehicle, pickerStatus, vehicle?.id, myVehicles.length]);

  const openPicker = useCallback(async () => {
    setPickerOpen(true);
    // Recharge le périmètre à l'ouverture (un véhicule peut être devenu non autorisé).
    await loadAuthorized();
  }, [loadAuthorized]);

  const selectVehicle = useCallback(async (v: Vehicle) => {
    if (switching) return;
    setSwitching(true);
    try {
      await claimVehicle(v.id);          // « Je conduis » — session active côté backend
      setPickerOpen(false);
      await loadVehicle();               // recharge le véhicule actif (source: serveur)
      await privateMode.refresh();       // recharge l'état PRO/PRIVÉ pour CE véhicule
      // km.refresh se déclenche via le changement de vehicle.id (useKmSummary)
    } catch {
      // pas de changement optimiste si le claim échoue (403 hors périmètre, réseau…)
    } finally {
      setSwitching(false);
    }
  }, [switching, loadVehicle, privateMode]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([loadVehicle(), loadAuthorized(), privateMode.refresh(), km.refresh()]);
    setRefreshing(false);
  }, [loadVehicle, loadAuthorized, privateMode, km]);

  // Véhicule à mettre en avant dans le picker : l'actif, sinon le défaut AUTORISÉ.
  const highlightId = vehicle?.id
    ?? (defaultVehicleId && myVehicles.some((v) => v.id === defaultVehicleId)
        ? defaultVehicleId
        : null);

  const st = privateMode.status.state;
  const isPrivate = st === 'PRIVATE';
  const isBusiness = st === 'BUSINESS';
  const isPending = st === 'PENDING_CONFIRMATION' || st === 'PRIVATE_REQUESTED' || st === 'BUSINESS_REQUESTED';
  const hasVehicle = !!vehicle?.id;
  const canToggle = hasVehicle && privateMode.status.allowed && !privateMode.busy && !isPending;

  const fmtKm = (v: number | null | undefined) =>
    (typeof v === 'number' ? `${v.toFixed(1)} km` : '—');

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.primary} />}
      >
        {/* --- Véhicule actuel --- */}
        <Text style={styles.sectionLabel}>Véhicule actuel</Text>
        <View style={styles.vehicleCard} testID="manual-vehicle-card">
          {loadingVehicle ? (
            <ActivityIndicator color={colors.primary} />
          ) : hasVehicle ? (
            <>
              <Text style={styles.vehiclePlate} testID="manual-vehicle-plate">{vehicle?.plate || 'Véhicule'}</Text>
              {vehicle?.model ? <Text style={styles.vehicleModel}>{vehicle.model}</Text> : null}
              <View style={styles.connRow}>
                <View style={[styles.dot, { backgroundColor: connected ? colors.success : colors.textMuted }]} />
                <Text style={styles.connText}>{connected ? 'Connecté' : 'Hors ligne'}</Text>
              </View>
            </>
          ) : (
            <Text style={styles.emptyText} testID="manual-no-vehicle">Aucun véhicule sélectionné</Text>
          )}

          <TouchableOpacity style={styles.changeBtn} onPress={openPicker} testID="manual-change-vehicle">
            <Text style={styles.changeBtnText}>Changer de véhicule</Text>
          </TouchableOpacity>
        </View>

        {/* --- PRO / PRIVÉ --- */}
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

        {/* aide contextuelle (sans jargon) */}
        {hasVehicle && privateMode.status.allowed ? (
          <Text style={styles.helpText} testID="manual-mode-help">
            {isPrivate
              ? (privateMode.privateOdometerSupported
                  ? 'Mode Privé actif. Votre position est masquée. Vos kilomètres privés continuent d’être comptabilisés.'
                  : 'Mode Privé actif. Votre position est masquée.')
              : isBusiness
              ? 'Mode Professionnel actif. Les nouveaux trajets seront enregistrés comme professionnels.'
              : isPending
              ? 'Changement en cours de confirmation…'
              : 'Sélectionnez votre mode.'}
          </Text>
        ) : null}

        {privateMode.error ? (
          <Text style={styles.errorText} testID="manual-mode-error">{privateMode.error}</Text>
        ) : null}

        {/* Timeout de confirmation : message honnête, jamais de faux PRO/PRIVÉ confirmé. */}
        {privateMode.timedOut && !isPending ? (
          <Text style={styles.errorText} testID="manual-mode-timeout">
            Commande envoyée mais état non confirmé. Vérifiez l’état du véhicule.
          </Text>
        ) : null}

        {/* --- Km Pro / Km Privé (aujourd'hui) --- */}
        <Text style={styles.sectionLabel}>Kilomètres — Aujourd’hui</Text>
        <View style={styles.kmRow}>
          <View style={styles.kmCard} testID="manual-km-pro">
            <Text style={styles.kmTitle}>Km Pro</Text>
            <Text style={styles.kmPeriod}>Aujourd’hui</Text>
            <Text style={[styles.kmValue, { color: colors.pro }]}>{km.loading ? '…' : fmtKm(km.proKm)}</Text>
          </View>
          <View style={styles.kmCard} testID="manual-km-private">
            <Text style={styles.kmTitle}>Km Privé</Text>
            <Text style={styles.kmPeriod}>Aujourd’hui</Text>
            <Text style={[styles.kmValue, { color: colors.text }]}>{km.loading ? '…' : fmtKm(km.privateKm)}</Text>
          </View>
        </View>

        {/* --- SOS Urgence (bas de l'écran) --- */}
        <SosButton isPrivate={isPrivate} />
      </ScrollView>

      {/* --- Modal : Choisir un véhicule (assignés uniquement) --- */}
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
                      style={[styles.vehicleRow, (isActive || isDefault) && styles.vehicleRowSelected]}
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
    >
      <Text style={[styles.modeLabel, active && { color }]}>{label}</Text>
      {loading ? <ActivityIndicator size="small" color={color} /> : (
        <Text style={styles.modeState}>{active ? 'Actif' : 'Activer'}</Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  content: { padding: spacing.md, paddingBottom: spacing.xxl },
  sectionLabel: {
    color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase',
    letterSpacing: 1, marginBottom: spacing.sm, marginTop: spacing.md,
  },
  vehicleCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg,
  },
  vehiclePlate: { color: colors.text, fontSize: font.size.xl, fontWeight: '700' },
  vehicleModel: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  connRow: { flexDirection: 'row', alignItems: 'center', marginTop: spacing.sm },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  connText: { color: colors.textMuted, fontSize: font.size.sm },
  emptyText: { color: colors.textMuted, fontSize: font.size.md, paddingVertical: spacing.md },
  changeBtn: {
    marginTop: spacing.md, backgroundColor: colors.primary, borderRadius: radius.md,
    paddingVertical: spacing.md, alignItems: 'center',
  },
  changeBtnText: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },

  modesRow: { flexDirection: 'row', gap: spacing.md },
  modeCard: {
    flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 2,
    borderColor: colors.border, paddingVertical: spacing.xl, alignItems: 'center',
  },
  modeCardDisabled: { opacity: 0.55 },
  modeLabel: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', marginBottom: 6 },
  modeState: { color: colors.textMuted, fontSize: font.size.sm },
  helpText: { color: colors.textMuted, fontSize: font.size.sm, marginTop: spacing.md, lineHeight: 20 },
  errorText: { color: colors.danger, fontSize: font.size.sm, marginTop: spacing.sm },

  kmRow: { flexDirection: 'row', gap: spacing.md },
  kmCard: {
    flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, alignItems: 'flex-start',
  },
  kmTitle: { color: colors.text, fontSize: font.size.sm, fontWeight: '600' },
  kmPeriod: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2, marginBottom: spacing.sm },
  kmValue: { fontSize: font.size.xl, fontWeight: '700' },

  modalBackdrop: { flex: 1, backgroundColor: '#00000099', justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: colors.bg, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    padding: spacing.lg, maxHeight: '75%',
  },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.md },
  modalTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '700' },
  modalClose: { color: colors.primary, fontSize: font.size.md },
  vehicleRow: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.sm,
  },
  vehicleRowSelected: { borderColor: colors.primary },
  retryBtn: {
    marginTop: spacing.md, alignSelf: 'flex-start', borderWidth: 1, borderColor: colors.primary,
    borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  retryBtnText: { color: colors.primary, fontWeight: '600', fontSize: font.size.md },
  rowPlate: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },
  rowModel: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  rowCurrent: { color: colors.primary, fontSize: font.size.xs, fontWeight: '600' },
});
