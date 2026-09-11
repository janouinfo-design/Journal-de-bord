import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, ActivityIndicator,
  Modal, Image, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import * as ImagePicker from 'expo-image-picker';
import { colors, spacing, radius, font } from '@/theme/colors';
import { getMyVehicle, SessionVehicle } from '@/api/ble';
import {
  listVehicleDocuments, uploadVehicleDocument, VehicleDocument,
  VehicleDocumentType, DOCUMENT_TYPE_LABEL, STATUS_LABEL,
} from '@/api/documents';

const TYPES: VehicleDocumentType[] = [
  'carte_grise', 'assurance', 'leasing', 'controle_technique', 'autre',
];

const STATUS_COLOR: Record<string, string> = {
  a_traiter: colors.warning,
  valide: colors.success,
  expire: colors.danger,
};

type Pending = { uri: string; name: string; mimeType: string } | null;

/**
 * Module DOCUMENTS — RÉEL (Phase 2), lié au Journal de bord.
 * Liste réelle du véhicule sélectionné, ajout photo/galerie -> backend (stockage + OCR serveur).
 * REAL DATA ONLY : aucune donnée fictive ; états loading/error/empty propres.
 */
export function DocumentsScreen() {
  const [vehicle, setVehicle] = useState<SessionVehicle | null>(null);
  const [docs, setDocs] = useState<VehicleDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [pending, setPending] = useState<Pending>(null);
  const [pendingType, setPendingType] = useState<VehicleDocumentType>('autre');
  const [uploading, setUploading] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const v = await getMyVehicle();
      setVehicle(v?.vehicle ?? null);
      if (v?.vehicle?.id) {
        const res = await listVehicleDocuments(v.vehicle.id);
        setDocs(res.documents);
      } else {
        setDocs([]);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Documents indisponibles. Vérifiez votre connexion.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Le changement de véhicule (session backend) rafraîchit la liste au focus/refresh.
  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  const pickFrom = useCallback(async (source: 'camera' | 'library') => {
    try {
      if (source === 'camera') {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) { Alert.alert('Autorisation requise', 'Accès caméra refusé.'); return; }
        const r = await ImagePicker.launchCameraAsync({ quality: 0.7 });
        if (!r.canceled && r.assets?.[0]) {
          const a = r.assets[0];
          setPending({ uri: a.uri, name: a.fileName || `photo_${Date.now()}.jpg`, mimeType: a.mimeType || 'image/jpeg' });
        }
      } else {
        const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) { Alert.alert('Autorisation requise', 'Accès galerie refusé.'); return; }
        const r = await ImagePicker.launchImageLibraryAsync({ quality: 0.7 });
        if (!r.canceled && r.assets?.[0]) {
          const a = r.assets[0];
          setPending({ uri: a.uri, name: a.fileName || `image_${Date.now()}.jpg`, mimeType: a.mimeType || 'image/jpeg' });
        }
      }
    } catch {
      Alert.alert('Erreur', "Impossible d'ouvrir la source. Réessayez.");
    }
  }, []);

  const submit = useCallback(async () => {
    if (inFlight.current || !pending || !vehicle?.id) return; // anti double-submit
    inFlight.current = true;
    setUploading(true);
    try {
      await uploadVehicleDocument({
        uri: pending.uri, name: pending.name, mimeType: pending.mimeType,
        type: pendingType, vehicleId: vehicle.id,
      });
      setAddOpen(false);
      setPending(null);
      setPendingType('autre');
      await load(); // recharge la liste réelle
    } catch (e: any) {
      Alert.alert('Envoi échoué', e?.response?.data?.detail || "Le document n'a pas pu être envoyé.");
    } finally {
      setUploading(false);
      inFlight.current = false;
    }
  }, [pending, pendingType, vehicle?.id, load]);

  const hasVehicle = !!vehicle?.id;

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text} />}
        testID="documents-scroll"
      >
        <Text style={styles.title}>Documents</Text>

        {/* En-tête véhicule/plaque sélectionné */}
        <View style={styles.headerCard} testID="documents-context">
          <Text style={styles.contextLabel}>Véhicule sélectionné</Text>
          <Text style={styles.plate} testID="documents-vehicle">
            {vehicle?.plate || 'Aucun véhicule sélectionné'}
          </Text>
          {vehicle?.model ? <Text style={styles.contextSub}>{vehicle.model}</Text> : null}
        </View>

        <TouchableOpacity
          style={[styles.addBtn, !hasVehicle && styles.addBtnDisabled]}
          onPress={() => setAddOpen(true)}
          disabled={!hasVehicle}
          testID="documents-add"
        >
          <Text style={styles.addBtnText}>+ Ajouter un document</Text>
        </TouchableOpacity>

        {loading ? (
          <ActivityIndicator style={{ marginTop: spacing.xl }} color={colors.primary} testID="documents-loading" />
        ) : error ? (
          <View style={styles.errorBox} testID="documents-error">
            <Text style={styles.errorText}>{error}</Text>
            <TouchableOpacity onPress={load} testID="documents-retry"><Text style={styles.retry}>Réessayer</Text></TouchableOpacity>
          </View>
        ) : docs.length === 0 ? (
          <View style={styles.emptyCard} testID="documents-empty">
            <Text style={styles.emptyBody}>Aucun document pour ce véhicule.</Text>
          </View>
        ) : (
          docs.map((d) => (
            <View key={d.id} style={styles.docRow} testID={`document-item-${d.id}`}>
              <View style={{ flex: 1 }}>
                <View style={styles.docTopRow}>
                  <View style={styles.typeBadge}><Text style={styles.typeBadgeText}>{DOCUMENT_TYPE_LABEL[d.type]}</Text></View>
                  <View style={[styles.statusBadge, { borderColor: STATUS_COLOR[d.status] }]}>
                    <Text style={[styles.statusText, { color: STATUS_COLOR[d.status] }]}>{STATUS_LABEL[d.status]}</Text>
                  </View>
                </View>
                <Text style={styles.docName}>{d.filename}</Text>
                {d.expiry_date ? (
                  <Text style={styles.docMeta}>Expire le {d.expiry_date}</Text>
                ) : d.document_date ? (
                  <Text style={styles.docMeta}>Daté du {d.document_date}</Text>
                ) : null}
              </View>
            </View>
          ))
        )}
      </ScrollView>

      {/* Modal : ajouter un document (source -> type -> aperçu -> envoi) */}
      <Modal visible={addOpen} transparent animationType="slide" onRequestClose={() => setAddOpen(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Ajouter un document</Text>
              <TouchableOpacity onPress={() => { setAddOpen(false); setPending(null); }} testID="documents-add-close">
                <Text style={styles.modalClose}>Fermer</Text>
              </TouchableOpacity>
            </View>

            {!pending ? (
              <View style={styles.sourceRow}>
                <TouchableOpacity style={styles.sourceBtn} onPress={() => pickFrom('camera')} testID="documents-camera">
                  <Text style={styles.sourceText}>Prendre une photo</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.sourceBtn} onPress={() => pickFrom('library')} testID="documents-import">
                  <Text style={styles.sourceText}>Importer</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <>
                <Image source={{ uri: pending.uri }} style={styles.preview} resizeMode="contain" testID="documents-preview" />
                <Text style={styles.typeLabel}>Type de document</Text>
                <View style={styles.typesWrap}>
                  {TYPES.map((t) => (
                    <TouchableOpacity
                      key={t}
                      style={[styles.typeChip, pendingType === t && styles.typeChipActive]}
                      onPress={() => setPendingType(t)}
                      testID={`documents-type-${t}`}
                    >
                      <Text style={[styles.typeChipText, pendingType === t && styles.typeChipTextActive]}>
                        {DOCUMENT_TYPE_LABEL[t]}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <TouchableOpacity
                  style={[styles.submitBtn, uploading && styles.submitBtnDisabled]}
                  onPress={submit}
                  disabled={uploading}
                  testID="documents-submit"
                >
                  {uploading ? <ActivityIndicator color={colors.text} /> : <Text style={styles.submitText}>Envoyer</Text>}
                </TouchableOpacity>
              </>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { padding: spacing.lg },
  title: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', marginBottom: spacing.md },
  headerCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md,
  },
  contextLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase', letterSpacing: 1 },
  plate: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', letterSpacing: 1, marginTop: 2 },
  contextSub: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  addBtn: {
    backgroundColor: colors.primary, borderRadius: radius.md, paddingVertical: spacing.md,
    alignItems: 'center', marginBottom: spacing.md,
  },
  addBtnDisabled: { opacity: 0.5 },
  addBtnText: { color: colors.text, fontSize: font.size.md, fontWeight: '700' },
  errorBox: {
    backgroundColor: 'rgba(239,68,68,0.12)', borderColor: colors.danger, borderWidth: 1,
    borderRadius: radius.md, padding: spacing.md,
  },
  errorText: { color: colors.danger, fontSize: font.size.sm },
  retry: { color: colors.primary, fontWeight: '600', marginTop: spacing.sm },
  emptyCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg,
  },
  emptyBody: { color: colors.textMuted, fontSize: font.size.sm },
  docRow: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bgCard,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.sm,
  },
  docTopRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.xs },
  typeBadge: { backgroundColor: 'rgba(59,130,246,0.18)', borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  typeBadgeText: { color: colors.text, fontSize: font.size.xs, fontWeight: '600' },
  statusBadge: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  statusText: { fontSize: font.size.xs, fontWeight: '700' },
  docName: { color: colors.text, fontSize: font.size.md, fontWeight: '600' },
  docMeta: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  modalBackdrop: { flex: 1, backgroundColor: '#00000099', justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: colors.bg, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    padding: spacing.lg, maxHeight: '85%',
  },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.md },
  modalTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '700' },
  modalClose: { color: colors.primary, fontSize: font.size.md },
  sourceRow: { flexDirection: 'row', gap: spacing.md },
  sourceBtn: {
    flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, paddingVertical: spacing.lg, alignItems: 'center',
  },
  sourceText: { color: colors.primary, fontSize: font.size.md, fontWeight: '600' },
  preview: { width: '100%', height: 220, borderRadius: radius.md, backgroundColor: colors.bgCard, marginBottom: spacing.md },
  typeLabel: { color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase', letterSpacing: 1, marginBottom: spacing.sm },
  typesWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md },
  typeChip: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  typeChipActive: { borderColor: colors.primary, backgroundColor: 'rgba(59,130,246,0.15)' },
  typeChipText: { color: colors.textMuted, fontSize: font.size.sm },
  typeChipTextActive: { color: colors.text, fontWeight: '700' },
  submitBtn: { backgroundColor: colors.success, borderRadius: radius.md, paddingVertical: spacing.md, alignItems: 'center' },
  submitBtnDisabled: { opacity: 0.6 },
  submitText: { color: colors.text, fontSize: font.size.md, fontWeight: '700' },
});
