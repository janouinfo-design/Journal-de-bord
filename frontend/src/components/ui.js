import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, radius, spacing, font } from '../theme/theme';

export function Card({ children, style, ...rest }) {
  return (
    <View style={[styles.card, style]} {...rest}>
      {children}
    </View>
  );
}

export function SectionTitle({ children, right }) {
  return (
    <View style={styles.sectionRow}>
      <Text style={styles.sectionTitle}>{children}</Text>
      {right}
    </View>
  );
}

export function Pill({ label, color = colors.textMuted, bg = colors.surfaceAlt, style, testID }) {
  return (
    <View style={[styles.pill, { backgroundColor: bg }, style]} testID={testID}>
      <Text style={[styles.pillText, { color }]}>{label}</Text>
    </View>
  );
}

export function Divider() {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
  },
  sectionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  sectionTitle: {
    color: colors.textMuted,
    fontSize: font.size.sm,
    fontWeight: font.weight.semibold,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  pill: {
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    borderRadius: radius.pill,
    alignSelf: 'flex-start',
  },
  pillText: { fontSize: font.size.xs, fontWeight: font.weight.semibold },
  divider: { height: 1, backgroundColor: colors.border, marginVertical: spacing.md },
});
