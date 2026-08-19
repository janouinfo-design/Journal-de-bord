import React, { useEffect, useState, useMemo, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { colors, spacing, radius, font } from '@/theme/colors';
import { useVehiclesStore } from '@/store/vehiclesStore';
import { Vehicle } from '@/api/ble';
import type { RootStackParamList } from '@/navigation/RootNavigator';

type PickerRoute = RouteProp<RootStackParamList, 'VehiclePicker'>;

/**
 * Écran plein écran de sélection de véhicule — pensé pour une flotte de 6 à 200+.
 * - FlatList virtualisée (rendu léger, pas de grille massive).
 * - Recherche locale debounced (plaque/marque/modèle), insensible casse + tolérante espaces.
 * - Au choix : renvoie le véhicule sélectionné à l'écran Conduite via un callback de route.
 */
export function VehiclePickerScreen() {
  const nav = useNavigation<any>();
  const route = useRoute<PickerRoute>();
  const onPick = route.params?.onPick;

  const { vehicles, loading, error, load, search } = useVehiclesStore();
  const [rawQuery, setRawQuery] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    load();
  }, [load]);

  // Debounce léger de la recherche (300 ms) pour rester fluide sur grande liste.
  useEffect(() => {
    const t = setTimeout(() => setQuery(rawQuery), 300);
    return () => clearTimeout(t);
  }, [rawQuery]);

  const results = useMemo(
    () => search(query),
    // `vehicles` est inclus volontairement : la recherche dépend de la flotte chargée.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query, vehicles],
  );

  const handlePick = useCallback(
    (v: Vehicle) => {
      if (onPick) onPick(v);
      nav.goBack();
    },
    [onPick, nav],
  );

  const renderItem = useCallback(
    ({ item }: { item: Vehicle }) => (
      <TouchableOpacity
        style={styles.row}
        onPress={() => handlePick(item)}
        testID={`vehicle-option-${item.plate}`}
      >
        <View style={{ flex: 1 }}>
          <Text style={styles.plate}>{item.plate || 'N/A'}</Text>
          {item.model ? <Text style={styles.model}>{item.model}</Text> : null}
        </View>
        <Text style={styles.chevron}>›</Text>
      </TouchableOpacity>
    ),
    [handlePick],
  );

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.searchBox}>
        <Text style={styles.searchIcon}>🔎</Text>
        <TextInput
          style={styles.searchInput}
          value={rawQuery}
          onChangeText={setRawQuery}
          placeholder="Rechercher plaque ou modèle"
          placeholderTextColor={colors.textMuted}
          autoCapitalize="none"
          autoCorrect={false}
          testID="vehicle-search-input"
        />
        {rawQuery ? (
          <TouchableOpacity onPress={() => setRawQuery('')} testID="vehicle-search-clear">
            <Text style={styles.clear}>✕</Text>
          </TouchableOpacity>
        ) : null}
      </View>

      <Text style={styles.count} testID="vehicle-count">
        {loading ? 'Chargement…' : `${results.length} véhicule${results.length > 1 ? 's' : ''}`}
      </Text>

      {loading && vehicles.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} size="large" />
        </View>
      ) : error && vehicles.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.error} testID="vehicle-error">
            {error}
          </Text>
          <TouchableOpacity style={styles.retryBtn} onPress={() => load(true)}>
            <Text style={styles.retryText}>Réessayer</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={results}
          keyExtractor={(v) => v.id}
          renderItem={renderItem}
          initialNumToRender={12}
          maxToRenderPerBatch={16}
          windowSize={10}
          removeClippedSubviews
          keyboardShouldPersistTaps="handled"
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.emptyText} testID="vehicle-empty">
                Aucun véhicule ne correspond à « {query} ».
              </Text>
            </View>
          }
          testID="vehicle-list"
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  searchBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginHorizontal: spacing.lg,
    marginTop: spacing.md,
    paddingHorizontal: spacing.md,
  },
  searchIcon: { fontSize: font.size.md, marginRight: spacing.sm },
  searchInput: { flex: 1, color: colors.text, fontSize: font.size.md, paddingVertical: spacing.md },
  clear: { color: colors.textMuted, fontSize: font.size.lg, paddingHorizontal: spacing.sm },
  count: {
    color: colors.textMuted,
    fontSize: font.size.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.sm,
    minHeight: 60,
  },
  plate: { color: colors.text, fontSize: font.size.lg, fontWeight: '600', letterSpacing: 1 },
  model: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  chevron: { color: colors.textMuted, fontSize: font.size.xl },
  emptyText: { color: colors.textMuted, fontSize: font.size.md, textAlign: 'center' },
  error: { color: colors.danger, fontSize: font.size.md, textAlign: 'center' },
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
