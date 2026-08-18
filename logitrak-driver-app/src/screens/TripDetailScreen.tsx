import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRoute, useNavigation, RouteProp } from '@react-navigation/native';
import { colors, spacing, radius, font } from '@/theme/colors';
import { useTripsStore } from '@/store/tripsStore';
import { getTrack, TrackResponse, Trip } from '@/api/trips';
import { showConfirm } from '@/utils/alert';
import {
  formatDate,
  formatTime,
  formatDuration,
  formatDistance,
  classificationBadge,
} from '@/utils/trip';
import type { RootStackParamList } from '@/navigation/RootNavigator';

type DetailRoute = RouteProp<RootStackParamList, 'TripDetail'>;

export function TripDetailScreen() {
  const route = useRoute<DetailRoute>();
  const nav = useNavigation();
  const { tripId } = route.params;
  const { trips, classify, classifyingId } = useTripsStore();
  const trip: Trip | undefined = trips.find((t) => t.id === tripId);

  const [track, setTrack] = useState<TrackResponse | null>(null);
  const [trackLoading, setTrackLoading] = useState(false);
  const [trackError, setTrackError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setTrackLoading(true);
      setTrackError(null);
      try {
        const t = await getTrack(tripId);
        if (!cancelled) setTrack(t);
      } catch (e: any) {
        if (!cancelled) {
          const status = e?.response?.status;
          setTrackError(
            status === 403
              ? 'Tracé masqué (trajet personnel).'
              : "Tracé indisponible pour ce trajet.",
          );
        }
      } finally {
        if (!cancelled) setTrackLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tripId]);

  const onReclassify = useCallback(
    (next: 'professional' | 'personal') => {
      const label = next === 'professional' ? 'PROFESSIONNEL' : 'PRIVÉ';
      showConfirm('Classer le trajet', `Marquer ce trajet comme ${label} ?`, [
        { text: 'Annuler', style: 'cancel' },
        {
          text: 'Confirmer',
          onPress: async () => {
            const res = await classify(tripId, next);
            if (!res.ok) showConfirm('Erreur', res.message || 'Échec de la classification.');
          },
        },
      ]);
    },
    [tripId, classify],
  );

  if (!trip) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <View style={styles.center}>
          <Text style={styles.muted}>Trajet introuvable. Revenez à la liste.</Text>
          <TouchableOpacity style={styles.retryBtn} onPress={() => nav.goBack()}>
            <Text style={styles.retryText}>Retour</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const badge = classificationBadge(trip.classification ?? null);
  const submitting = classifyingId === tripId;

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.scroll} testID="trip-detail-scroll">
        {/* En-tête */}
        <View style={styles.headerCard}>
          <View style={[styles.badge, { backgroundColor: badge.bg, alignSelf: 'flex-start' }]}>
            <Text style={[styles.badgeText, { color: badge.color }]}>{badge.label}</Text>
          </View>
          <Text style={styles.dateBig}>
            {formatDate(trip.start_time)} · {formatTime(trip.start_time)} → {formatTime(trip.end_time)}
          </Text>
          <Text style={styles.vehicle}>{trip.vehicle_plate || 'Véhicule N/A'}</Text>
        </View>

        {/* Itinéraire (adresses réelles) */}
        <Section title="Itinéraire">
          <Row label="Origine" value={trip.start_address || 'N/A'} />
          <Row label="Destination" value={trip.end_address || 'N/A'} />
        </Section>

        {/* Mesures réelles */}
        <Section title="Détails">
          <Row label="Distance" value={formatDistance(trip.distance_km)} />
          <Row label="Durée" value={formatDuration(trip.duration_min)} />
          <Row
            label="Vitesse moy."
            value={trip.avg_speed != null ? `${trip.avg_speed} km/h` : 'N/A'}
          />
          <Row
            label="Vitesse max."
            value={trip.max_speed != null ? `${trip.max_speed} km/h` : 'N/A'}
          />
          <Row label="Carburant" value={trip.fuel_l != null ? `${trip.fuel_l} L` : 'N/A'} />
        </Section>

        {/* Tracé : visualisation simple (données réelles uniquement) */}
        <Section title="Tracé">
          {trackLoading ? (
            <ActivityIndicator color={colors.primary} />
          ) : trackError ? (
            <Text style={styles.muted} testID="trip-track-error">
              {trackError}
            </Text>
          ) : track && track.points?.length ? (
            <MiniTrack track={track} />
          ) : (
            <Text style={styles.muted}>Aucun point GPS disponible.</Text>
          )}
        </Section>

        {/* Reclassification */}
        <Section title="Classification">
          <View style={styles.classifyRow}>
            <TouchableOpacity
              style={[
                styles.classifyBtn,
                trip.classification === 'professional' && styles.classifyBtnActivePro,
              ]}
              disabled={submitting}
              onPress={() => onReclassify('professional')}
              testID="trip-classify-pro"
            >
              <Text style={styles.classifyBtnText}>{submitting ? '…' : 'PRO'}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.classifyBtn,
                trip.classification === 'personal' && styles.classifyBtnActivePerso,
              ]}
              disabled={submitting}
              onPress={() => onReclassify('personal')}
              testID="trip-classify-perso"
            >
              <Text style={styles.classifyBtnText}>{submitting ? '…' : 'PRIVÉ'}</Text>
            </TouchableOpacity>
          </View>
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

// Visualisation minimale du tracé : nombre de points + coordonnées début/fin réelles.
function MiniTrack({ track }: { track: TrackResponse }) {
  const first = track.points[0];
  const last = track.points[track.points.length - 1];
  return (
    <View>
      <Text style={styles.trackInfo}>{track.count} point(s) GPS · source : {track.source}</Text>
      {first ? (
        <Text style={styles.trackCoord}>
          Départ : {first[1].toFixed(4)}, {first[0].toFixed(4)}
        </Text>
      ) : null}
      {last ? (
        <Text style={styles.trackCoord}>
          Arrivée : {last[1].toFixed(4)}, {last[0].toFixed(4)}
        </Text>
      ) : null}
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  muted: { color: colors.textMuted, fontSize: font.size.sm },
  scroll: { padding: spacing.lg },
  headerCard: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  badge: { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.pill },
  badgeText: { fontSize: font.size.xs, fontWeight: '700' },
  dateBig: { color: colors.text, fontSize: font.size.md, fontWeight: '600', marginTop: spacing.sm },
  vehicle: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  section: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  sectionBody: {},
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
  },
  rowLabel: { color: colors.textMuted, fontSize: font.size.sm },
  rowValue: { color: colors.text, fontSize: font.size.sm, fontWeight: '500', flexShrink: 1, textAlign: 'right' },
  trackInfo: { color: colors.text, fontSize: font.size.sm, marginBottom: spacing.xs },
  trackCoord: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  classifyRow: { flexDirection: 'row', gap: spacing.md },
  classifyBtn: {
    flex: 1,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  classifyBtnActivePro: { borderColor: colors.primary, backgroundColor: 'rgba(59,130,246,0.12)' },
  classifyBtnActivePerso: { borderColor: colors.perso, backgroundColor: 'rgba(71,85,105,0.18)' },
  classifyBtnText: { color: colors.text, fontWeight: '700', letterSpacing: 1 },
  retryBtn: {
    marginTop: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  retryText: { color: colors.primary, fontWeight: '600' },
});
