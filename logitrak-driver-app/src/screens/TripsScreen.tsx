import React, { useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors, spacing, radius, font } from '@/theme/colors';
import { useTripsStore } from '@/store/tripsStore';
import { Trip } from '@/api/trips';
import {
  formatDate,
  formatTime,
  formatDuration,
  formatDistance,
  classificationBadge,
  tripRouteLabel,
} from '@/utils/trip';
import type { RootStackParamList } from '@/navigation/RootNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function TripsScreen() {
  const nav = useNavigation<Nav>();
  const { trips, loading, error, load, refresh } = useTripsStore();
  const [refreshing, setRefreshing] = React.useState(false);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
  }, [refresh]);

  const renderItem = useCallback(
    ({ item }: { item: Trip }) => {
      const badge = classificationBadge(item.classification ?? null);
      const route = tripRouteLabel(item);
      return (
        <TouchableOpacity
          style={styles.card}
          onPress={() => nav.navigate('TripDetail', { tripId: item.id })}
          testID={`trip-item-${item.id}`}
        >
          <View style={styles.cardHeader}>
            <Text style={styles.date}>
              {formatDate(item.start_time)} · {formatTime(item.start_time)}
            </Text>
            <View style={[styles.badge, { backgroundColor: badge.bg }]}>
              <Text style={[styles.badgeText, { color: badge.color }]}>{badge.label}</Text>
            </View>
          </View>

          <Text style={styles.route} numberOfLines={1}>
            {route.from}
          </Text>
          <Text style={styles.routeArrow}>↓</Text>
          <Text style={styles.route} numberOfLines={1}>
            {route.to}
          </Text>

          <View style={styles.metaRow}>
            <Meta label={item.vehicle_plate || 'N/A'} />
            <Meta label={formatDistance(item.distance_km)} />
            <Meta label={formatDuration(item.duration_min)} />
          </View>
        </TouchableOpacity>
      );
    },
    [nav],
  );

  if (loading && trips.length === 0) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} size="large" />
          <Text style={styles.centerText}>Chargement de vos trajets…</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (error && trips.length === 0) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <View style={styles.center}>
          <Text style={styles.errorTitle} testID="trips-error">
            {error}
          </Text>
          <TouchableOpacity style={styles.retryBtn} onPress={load} testID="trips-retry">
            <Text style={styles.retryText}>Réessayer</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <FlatList
        data={trips}
        keyExtractor={(t) => t.id}
        renderItem={renderItem}
        contentContainerStyle={
          trips.length === 0 ? styles.emptyContainer : styles.listContent
        }
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text} />
        }
        ListEmptyComponent={
          <View style={styles.center}>
            <Text style={styles.emptyTitle} testID="trips-empty">
              Aucun trajet disponible
            </Text>
            <Text style={styles.emptySub}>
              Vos trajets apparaîtront ici dès qu'ils seront enregistrés.
            </Text>
          </View>
        }
        testID="trips-list"
      />
    </SafeAreaView>
  );
}

function Meta({ label }: { label: string }) {
  return (
    <View style={styles.metaChip}>
      <Text style={styles.metaText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  centerText: { color: colors.textMuted, marginTop: spacing.md, fontSize: font.size.md },
  listContent: { padding: spacing.lg },
  emptyContainer: { flexGrow: 1 },
  emptyTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  emptySub: {
    color: colors.textMuted,
    fontSize: font.size.sm,
    marginTop: spacing.sm,
    textAlign: 'center',
  },
  errorTitle: { color: colors.danger, fontSize: font.size.md, textAlign: 'center' },
  retryBtn: {
    marginTop: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  retryText: { color: colors.primary, fontWeight: '600' },
  card: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  date: { color: colors.textMuted, fontSize: font.size.sm },
  badge: { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.pill },
  badgeText: { fontSize: font.size.xs, fontWeight: '700' },
  route: { color: colors.text, fontSize: font.size.md, fontWeight: '500' },
  routeArrow: { color: colors.textMuted, fontSize: font.size.sm, marginVertical: 2 },
  metaRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md, flexWrap: 'wrap' },
  metaChip: {
    backgroundColor: colors.bg,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: colors.border,
  },
  metaText: { color: colors.textMuted, fontSize: font.size.xs },
});
