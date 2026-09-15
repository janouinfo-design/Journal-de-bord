import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, ActivityIndicator,
  TextInput, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import { colors, spacing, radius, font } from '@/theme/colors';
import { getMyVehicle, getMyProfile, SessionVehicle } from '@/api/ble';
import {
  createInspection, getCurrentInspection, listInspections, saveChecklist,
  addInspectionPhoto, deleteInspectionPhoto, validateInspection,
  Inspection, ItemState, ChecklistEntry, CHECKLIST_LABEL,
} from '@/api/inspections';

const STATES: ItemState[] = ['OK', 'ANOMALIE', 'N/A'];
const STATE_COLOR: Record<string, string> = { OK: colors.success, ANOMALIE: colors.danger, 'N/A': colors.textMuted };

/**
 * Module INSPECTION — RÉEL (Phase 3), lié au Journal de bord.
 * Workflow : nouvelle inspection -> checklist (OK/ANOMALIE/N/A) -> anomalie (commentaire + photo)
 * -> validation. Historique réel. REAL DATA ONLY. Le véhicule/chauffeur sont figés serveur.
 */
export function InspectionScreen() {
  const [vehicle, setVehicle] = useState<SessionVehicle | null>(null);
  const [driverName, setDriverName] = useState<string | null>(null);
  const [history, setHistory] = useState<Inspection[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Inspection en cours d'édition (mode workflow).
  const [current, setCurrent] = useState<Inspection | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [v, p] = await Promise.all([getMyVehicle(), getMyProfile()]);
      setVehicle(v?.vehicle ?? null);
      setDriverName(p?.name ?? null);
      if (v?.vehicle?.id) {
        setHistory(await listInspections(v.vehicle.id));
      } else {
        setHistory([]);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Inspections indisponibles. Vérifiez votre connexion.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  const startInspection = useCallback(async () => {
    if (inFlight.current || !vehicle?.id) return;
    inFlight.current = true; setBusy(true);
    try {
      setCurrent(await createInspection(vehicle.id));
    } catch (e: any) {
      Alert.alert('Erreur', e?.response?.data?.detail || 'Impossible de démarrer l’inspection.');
    } finally { setBusy(false); inFlight.current = false; }
  }, [vehicle?.id]);

  const setItemState = useCallback((item: string, state: ItemState) => {
    setCurrent((prev) => prev ? {
      ...prev,
      checklist: prev.checklist.map((c) => c.item === item ? { ...c, state } : c),
    } : prev);
  }, []);

  const setItemComment = useCallback((item: string, comment: string) => {
    setCurrent((prev) => prev ? {
      ...prev,
      checklist: prev.checklist.map((c) => c.item === item ? { ...c, comment } : c),
    } : prev);
  }, []);

  const persistChecklist = useCallback(async (insp: Inspection) => {
    const items = insp.checklist
      .filter((c) => c.state)
      .map((c) => ({ item: c.item, state: c.state as ItemState, comment: c.comment ?? undefined }));
    return saveChecklist(insp.id, items, insp.general_comment ?? undefined);
  }, []);

  const addPhoto = useCallback(async (item: string) => {
    if (!current) return;
    try {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) { Alert.alert('Autorisation requise', 'Accès caméra refusé.'); return; }
      const r = await ImagePicker.launchCameraAsync({ quality: 0.6 });
      if (r.canceled || !r.assets?.[0]) return;
      const a = r.assets[0];
      // Sauvegarde d'abord l'état de la checklist (pour ne pas perdre les saisies), puis la photo.
      await persistChecklist(current);
      await addInspectionPhoto(current.id, item, {
        uri: a.uri, name: a.fileName || `photo_${Date.now()}.jpg`, mimeType: a.mimeType || 'image/jpeg',
      });
      setCurrent(await getCurrentInspection(vehicle?.id));
    } catch (e: any) {
      Alert.alert('Photo', e?.response?.data?.detail || "La photo n'a pas pu être ajoutée.");
    }
  }, [current, vehicle?.id, persistChecklist]);

  const removePhoto = useCallback(async (photoId: string) => {
    if (!current) return;
    try {
      await deleteInspectionPhoto(current.id, photoId);
      setCurrent(await getCurrentInspection(vehicle?.id));
    } catch (e: any) {
      Alert.alert('Photo', e?.response?.data?.detail || 'Suppression impossible.');
    }
  }, [current, vehicle?.id]);

  const validate = useCallback(async () => {
    if (inFlight.current || !current) return; // anti double-submit
    // Règle : chaque ANOMALIE doit avoir un commentaire.
    const missing = current.checklist.find((c) => c.state === 'ANOMALIE' && !(c.comment || '').trim());
    if (missing) {
      Alert.alert('Commentaire requis', `Ajoutez un commentaire pour l’anomalie : ${CHECKLIST_LABEL[missing.item]}`);
      return;
    }
    inFlight.current = true; setBusy(true);
    try {
      await persistChecklist(current);       // sauvegarde finale
      await validateInspection(current.id);   // validation (immuable ensuite)
      setCurrent(null);
      await load();                            // recharge l'historique réel
    } catch (e: any) {
      Alert.alert('Validation', e?.response?.data?.detail || 'Validation impossible.');
    } finally { setBusy(false); inFlight.current = false; }
  }, [current, persistChecklist, load]);

  const hasVehicle = !!vehicle?.id;

  // ---------- Mode ÉDITION (inspection en cours) ----------
  if (current) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <ScrollView contentContainerStyle={styles.scroll} testID="inspection-editor">
          <Text style={styles.title}>Inspection en cours</Text>
          <Text style={styles.subPlate}>{current.vehicle_snapshot?.plate || vehicle?.plate}</Text>

          {current.checklist.map((c) => (
            <View key={c.item} style={styles.itemCard} testID={`inspection-item-${c.item}`}>
              <Text style={styles.itemLabel}>{CHECKLIST_LABEL[c.item] || c.item}</Text>
              <View style={styles.statesRow}>
                {STATES.map((s) => (
                  <TouchableOpacity
                    key={s}
                    style={[styles.stateBtn, c.state === s && { borderColor: STATE_COLOR[s], backgroundColor: STATE_COLOR[s] + '22' }]}
                    onPress={() => setItemState(c.item, s)}
                    testID={`inspection-item-${c.item}-${s}`}
                  >
                    <Text style={[styles.stateText, c.state === s && { color: STATE_COLOR[s], fontWeight: '700' }]}>{s}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              {c.state === 'ANOMALIE' ? (
                <View style={styles.anomalyBox}>
                  <TextInput
                    style={styles.commentInput}
                    placeholder="Commentaire (obligatoire)"
                    placeholderTextColor={colors.textMuted}
                    value={c.comment || ''}
                    onChangeText={(t) => setItemComment(c.item, t)}
                    multiline
                    testID={`inspection-item-${c.item}-comment`}
                  />
                  <View style={styles.photosRow}>
                    {(c.photos || []).map((p) => (
                      <TouchableOpacity key={p.id} onPress={() => removePhoto(p.id)} testID={`inspection-photo-${p.id}`}>
                        <View style={styles.photoChip}><Text style={styles.photoChipText}>🖼 {p.filename.slice(0, 10)} ✕</Text></View>
                      </TouchableOpacity>
                    ))}
                    <TouchableOpacity style={styles.addPhotoBtn} onPress={() => addPhoto(c.item)} testID={`inspection-item-${c.item}-addphoto`}>
                      <Text style={styles.addPhotoText}>+ Photo</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              ) : null}
            </View>
          ))}

          <TouchableOpacity
            style={[styles.validateBtn, busy && styles.btnDisabled]}
            onPress={validate}
            disabled={busy}
            testID="inspection-validate"
          >
            {busy ? <ActivityIndicator color={colors.text} /> : <Text style={styles.validateText}>Valider l’inspection</Text>}
          </TouchableOpacity>
          <TouchableOpacity style={styles.cancelBtn} onPress={() => setCurrent(null)} disabled={busy} testID="inspection-cancel">
            <Text style={styles.cancelText}>Revenir plus tard</Text>
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------- Mode ACCUEIL (contexte + historique) ----------
  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text} />}
        testID="inspection-scroll"
      >
        <Text style={styles.title}>Inspection du véhicule</Text>

        <View style={styles.headerCard} testID="inspection-context">
          <Text style={styles.contextLabel}>Véhicule</Text>
          <Text style={styles.plate} testID="inspection-vehicle-plate">
            {vehicle?.plate || 'Aucun véhicule sélectionné'}
          </Text>
          {vehicle?.model ? <Text style={styles.contextSub}>{vehicle.model}</Text> : null}
          <Text style={[styles.contextLabel, { marginTop: spacing.sm }]}>Chauffeur</Text>
          <Text style={styles.contextValue} testID="inspection-driver">{driverName || '—'}</Text>
        </View>

        <TouchableOpacity
          style={[styles.newBtn, (!hasVehicle || busy) && styles.btnDisabled]}
          onPress={startInspection}
          disabled={!hasVehicle || busy}
          testID="inspection-new"
        >
          {busy ? <ActivityIndicator color={colors.text} /> : <Text style={styles.newBtnText}>Nouvelle inspection</Text>}
        </TouchableOpacity>

        <Text style={styles.sectionLabel}>Historique</Text>
        {loading ? (
          <ActivityIndicator color={colors.primary} testID="inspection-loading" />
        ) : error ? (
          <View style={styles.errorBox} testID="inspection-error">
            <Text style={styles.errorText}>{error}</Text>
            <TouchableOpacity onPress={load} testID="inspection-retry"><Text style={styles.retry}>Réessayer</Text></TouchableOpacity>
          </View>
        ) : history.length === 0 ? (
          <View style={styles.emptyCard} testID="inspection-history-empty">
            <Text style={styles.emptyBody}>Aucune inspection pour ce véhicule.</Text>
          </View>
        ) : (
          history.map((insp) => {
            const anomalies = insp.checklist.filter((c) => c.state === 'ANOMALIE').length;
            return (
              <View key={insp.id} style={styles.histRow} testID={`inspection-hist-${insp.id}`}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.histDate}>{(insp.validated_at || insp.created_at || '').slice(0, 16).replace('T', ' ')}</Text>
                  <Text style={styles.histMeta}>
                    {insp.status === 'validated' ? 'Validée' : 'En cours'} · {anomalies} anomalie{anomalies > 1 ? 's' : ''}
                  </Text>
                </View>
                <View style={[styles.statusBadge, { borderColor: insp.status === 'validated' ? colors.success : colors.warning }]}>
                  <Text style={[styles.statusText, { color: insp.status === 'validated' ? colors.success : colors.warning }]}>
                    {insp.status === 'validated' ? 'OK' : '…'}
                  </Text>
                </View>
              </View>
            );
          })
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { padding: spacing.lg },
  title: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', marginBottom: spacing.md },
  subPlate: { color: colors.textMuted, fontSize: font.size.md, marginBottom: spacing.md },
  headerCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md,
  },
  contextLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase', letterSpacing: 1 },
  contextValue: { color: colors.text, fontSize: font.size.md, fontWeight: '600', marginTop: 2 },
  plate: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', letterSpacing: 1, marginTop: 2 },
  contextSub: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  newBtn: { backgroundColor: colors.primary, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: 'center', marginBottom: spacing.lg },
  newBtnText: { color: colors.text, fontSize: font.size.md, fontWeight: '700' },
  btnDisabled: { opacity: 0.5 },
  sectionLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.sm },
  errorBox: { backgroundColor: 'rgba(239,68,68,0.12)', borderColor: colors.danger, borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  errorText: { color: colors.danger, fontSize: font.size.sm },
  retry: { color: colors.primary, fontWeight: '600', marginTop: spacing.sm },
  emptyCard: { backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg },
  emptyBody: { color: colors.textMuted, fontSize: font.size.sm },
  histRow: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm,
  },
  histDate: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },
  histMeta: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  statusBadge: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  statusText: { fontSize: font.size.xs, fontWeight: '700' },
  // Éditeur
  itemCard: { backgroundColor: colors.bgCard, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  itemLabel: { color: colors.text, fontSize: font.size.md, fontWeight: '600', marginBottom: spacing.sm },
  statesRow: { flexDirection: 'row', gap: spacing.sm },
  stateBtn: { flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center' },
  stateText: { color: colors.textMuted, fontSize: font.size.sm },
  anomalyBox: { marginTop: spacing.sm },
  commentInput: {
    color: colors.text, backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.sm, minHeight: 44, fontSize: font.size.sm,
  },
  photosRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginTop: spacing.sm, alignItems: 'center' },
  photoChip: { backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 4 },
  photoChipText: { color: colors.textMuted, fontSize: font.size.xs },
  addPhotoBtn: { borderWidth: 1, borderColor: colors.primary, borderRadius: radius.pill, paddingHorizontal: spacing.md, paddingVertical: 4 },
  addPhotoText: { color: colors.primary, fontSize: font.size.xs, fontWeight: '600' },
  validateBtn: { backgroundColor: colors.success, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: 'center', marginTop: spacing.md },
  validateText: { color: colors.text, fontSize: font.size.md, fontWeight: '700' },
  cancelBtn: { alignItems: 'center', paddingVertical: spacing.md, marginTop: spacing.sm },
  cancelText: { color: colors.textMuted, fontSize: font.size.sm },
});
