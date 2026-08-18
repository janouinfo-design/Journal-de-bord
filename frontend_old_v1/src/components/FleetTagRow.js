import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { colors, spacing, radius, font } from '../theme/theme';
import { signalQuality, tagLabel } from '../services/detection';

/**
 * Ligne d'un tag BLE de la flotte.
 * Affiche le dernier RSSI réel mesuré (si détecté), le nombre de détections,
 * et un bouton "Tester" (envoie une détection réelle au backend).
 */
export default function FleetTagRow({ tag, live, onTest, testing, index }) {
  const detected = !!live && live.count > 0;
  const sig = detected ? signalQuality(live.avgRssi) : null;

  return (
    <View style={[styles.row, index === 0 && styles.firstRow]}>
      <View style={[styles.dot, { backgroundColor: detected ? colors.success : colors.textFaint }]} />
      <View style={styles.info}>
        <Text style={styles.name} numberOfLines={1}>{tagLabel(tag)}</Text>
        <Text style={styles.meta} numberOfLines={1}>
          {tag?.mac || tag?.uuid || tag?.id || 'ID inconnu'}
        </Text>
      </View>

      <View style={styles.signalCol}>
        {detected ? (
          <>
            <Text style={[styles.rssi, { color: sig.color }]}>{live.avgRssi} dBm</Text>
            <Text style={styles.count}>{live.count} dét.</Text>
          </>
        ) : (
          <Text style={styles.noSignal}>—</Text>
        )}
      </View>

      <Pressable
        testID={`fleet-tag-test-${index}`}
        onPress={() => onTest && onTest(tag)}
        style={({ pressed }) => [styles.testBtn, pressed && styles.testBtnPressed]}
      >
        <Text style={styles.testBtnText}>{testing ? '…' : 'Tester'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: spacing.md,
  },
  firstRow: { borderTopWidth: 0 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  info: { flex: 1 },
  name: { color: colors.text, fontSize: font.size.md, fontWeight: font.weight.semibold },
  meta: { color: colors.textFaint, fontSize: font.size.xs, marginTop: 2 },
  signalCol: { alignItems: 'flex-end', minWidth: 64 },
  rssi: { fontSize: font.size.sm, fontWeight: font.weight.semibold },
  count: { color: colors.textFaint, fontSize: 10, marginTop: 2 },
  noSignal: { color: colors.textFaint, fontSize: font.size.md },
  testBtn: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  testBtnPressed: { backgroundColor: colors.surfaceAlt },
  testBtnText: { color: colors.primary, fontSize: font.size.sm, fontWeight: font.weight.semibold },
});
