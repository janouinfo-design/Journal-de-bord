import React, { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, radius, font } from '@/theme/colors';
import { getMyVehicle, getMyProfile, SessionVehicle } from '@/api/ble';

/**
 * Module INSPECTION VÉHICULE — SHELL (Phase 1).
 *
 * L'inspection est TOUJOURS rattachée au véhicule actuellement sélectionné (contexte réel
 * via /driver/my-vehicle) et au chauffeur courant (/driver/my-profile). Le tenant et la date
 * seront enregistrés côté serveur lors de la Phase 2 « Inspection réel ».
 *
 * REAL DATA ONLY : aucune API d'inspection n'existe encore côté backend Journal. On n'affiche
 * donc AUCUNE inspection fictive et AUCUN historique inventé. Le bouton « Nouvelle inspection »
 * et l'historique seront activés quand l'API réelle existera.
 */
export function InspectionScreen() {
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

  const hasVehicle = !!vehicle?.id;

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text} />}
        testID="inspection-scroll"
      >
        <Text style={styles.title}>Inspection du véhicule</Text>

        {/* Contexte réel : véhicule sélectionné + plaque + chauffeur */}
        <View style={styles.contextCard} testID="inspection-context">
          {loading ? (
            <ActivityIndicator color={colors.primary} />
          ) : (
            <>
              <Text style={styles.contextLabel}>Véhicule</Text>
              <Text style={styles.plate} testID="inspection-vehicle-plate">
                {vehicle?.plate || 'Aucun véhicule sélectionné'}
              </Text>
              {vehicle?.model ? <Text style={styles.contextSub}>{vehicle.model}</Text> : null}
              <Text style={[styles.contextLabel, { marginTop: spacing.sm }]}>Chauffeur</Text>
              <Text style={styles.contextValue} testID="inspection-driver">{driverName || '—'}</Text>
            </>
          )}
        </View>

        {error ? <Text style={styles.errorText} testID="inspection-error">{error}</Text> : null}

        {/* Nouvelle inspection — préparée (Phase 2), désactivée sans véhicule / sans API */}
        <TouchableOpacity
          style={[styles.newBtn, !hasVehicle && styles.newBtnDisabled]}
          disabled
          testID="inspection-new"
        >
          <Text style={styles.newBtnText}>Nouvelle inspection</Text>
        </TouchableOpacity>
        <Text style={styles.hint} testID="inspection-hint">
          La checklist (OK / Anomalie / N/A), les photos d’anomalie et la validation seront
          activées à l’étape suivante. Une inspection validée restera liée au véhicule et au
          chauffeur enregistrés (aucun changement silencieux).
        </Text>

        {/* Historique — état honnête, aucune donnée fictive */}
        <Text style={styles.sectionLabel}>Historique</Text>
        <View style={styles.emptyCard} testID="inspection-history-empty">
          <Text style={styles.emptyBody}>
            Aucun historique d’inspection disponible pour le moment.
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
  contextValue: { color: colors.text, fontSize: font.size.md, fontWeight: '600', marginTop: 2 },
  plate: { color: colors.text, fontSize: font.size.xl, fontWeight: '700', letterSpacing: 1, marginTop: 2 },
  contextSub: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  errorText: { color: colors.danger, fontSize: font.size.sm, marginBottom: spacing.md },
  newBtn: {
    backgroundColor: colors.primary, borderRadius: radius.md, paddingVertical: spacing.md,
    alignItems: 'center', opacity: 0.55,
  },
  newBtnDisabled: { opacity: 0.4 },
  newBtnText: { color: colors.text, fontSize: font.size.md, fontWeight: '700' },
  hint: { color: colors.textMuted, fontSize: font.size.sm, lineHeight: 20, marginTop: spacing.sm, marginBottom: spacing.lg },
  sectionLabel: {
    color: colors.textMuted, fontSize: font.size.xs, textTransform: 'uppercase',
    letterSpacing: 1, marginBottom: spacing.sm,
  },
  emptyCard: {
    backgroundColor: colors.bgCard, borderRadius: radius.lg, borderWidth: 1,
    borderColor: colors.border, padding: spacing.lg,
  },
  emptyBody: { color: colors.textMuted, fontSize: font.size.sm, lineHeight: 20 },
});
