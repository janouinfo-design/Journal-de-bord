import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, radius, font } from '@/theme/colors';
import { getMyVehicle, getMyProfile, SessionVehicle } from '@/api/ble';

/**
 * Module DOCUMENTS — SHELL (Phase 1).
 *
 * Objectif Phase 1 : préparer l'UI + câbler le CONTEXTE RÉEL (chauffeur + véhicule
 * sélectionné, via les API Journal existantes /driver/my-vehicle & /driver/my-profile).
 *
 * REAL DATA ONLY : aucune API générique de documents chauffeur/véhicule n'existe encore
 * côté backend Journal (les documents actuels sont rattachés aux amendes/cartes carburant).
 * On n'invente donc AUCUN document. La liste réelle + l'upload (réutilisant le pipeline
 * scanner/OCR serveur) seront branchés en Phase 2 « Documents réel ».
 */
export function DocumentsScreen() {
  const [vehicle, setVehicle] = useState<SessionVehicle | null>(null);
  const [driverName, setDriverName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [v, p] = await Promise.all([getMyVehicle(), getMyProfile()]);
      setVehicle(v?.vehicle ?? null);
      setDriverName(p?.name ?? null);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Contexte indisponible. Vérifiez votre connexion.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = useCallback(() => { setRefreshing(true); load(); }, [load]);

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text} />}
        testID="documents-scroll"
      >
        <Text style={styles.title}>Documents</Text>

        {/* Contexte réel : chauffeur + véhicule sélectionné */}
        <View style={styles.contextCard} testID="documents-context">
          {loading ? (
            <ActivityIndicator color={colors.primary} />
          ) : (
            <>
              <Text style={styles.contextLabel}>Chauffeur</Text>
              <Text style={styles.contextValue} testID="documents-driver">{driverName || '—'}</Text>
              <Text style={[styles.contextLabel, { marginTop: spacing.sm }]}>Véhicule sélectionné</Text>
              <Text style={styles.contextValue} testID="documents-vehicle">
                {vehicle?.plate || 'Aucun véhicule sélectionné'}
              </Text>
              {vehicle?.model ? <Text style={styles.contextSub}>{vehicle.model}</Text> : null}
            </>
          )}
        </View>

        {error ? <Text style={styles.errorText} testID="documents-error">{error}</Text> : null}

        {/* Actions d'ajout — préparées, branchées au Journal en Phase 2 */}
        <View style={styles.actionsRow}>
          <TouchableOpacity style={styles.actionBtn} disabled testID="documents-camera">
            <Text style={styles.actionText}>Prendre une photo</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.actionBtn} disabled testID="documents-import">
            <Text style={styles.actionText}>Importer</Text>
          </TouchableOpacity>
        </View>

        {/* État honnête : pas de données fictives */}
        <View style={styles.emptyCard} testID="documents-empty">
          <Text style={styles.emptyTitle}>Aucun document pour le moment</Text>
          <Text style={styles.emptyBody}>
            La connexion au Journal de bord (liste, ajout photo/galerie, scanner/OCR, statut
            à traiter / validé / expiré) sera activée à l’étape suivante. Aucune donnée fictive
            n’est affichée.
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { padding: spacing.lg },
  title: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', marginBottom: spacing.md },
  contextCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md,
  },
  contextLabel: {
    color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase', letterSpacing: 1,
  },
  contextValue: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', marginTop: 2 },
  contextSub: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  errorText: { color: colors.danger, fontSize: font.size.sm, marginBottom: spacing.md },
  actionsRow: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.md },
  actionBtn: {
    flex: 1, backgroundColor: colors.bgCard, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, paddingVertical: spacing.md, alignItems: 'center', opacity: 0.55,
  },
  actionText: { color: colors.primary, fontSize: font.size.md, fontWeight: '600' },
  emptyCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg,
  },
  emptyTitle: { color: colors.text, fontSize: font.size.md, fontWeight: '600', marginBottom: spacing.xs },
  emptyBody: { color: colors.textMuted, fontSize: font.size.sm, lineHeight: 20 },
});
