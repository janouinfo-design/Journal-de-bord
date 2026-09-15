import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { colors, spacing, radius, font } from '@/theme/colors';

export type SegmentOption<T extends string> = { value: T; label: string };

/**
 * Segmented control compact et premium (dark). Un seul segment actif à la fois.
 * - Segment actif : fond bleu LOGITRAK, texte blanc.
 * - Segments inactifs : fond sombre, texte atténué.
 * Accessibilité : role tab + selected + label. Ne dépend pas QUE de la couleur
 * (le segment actif est aussi plus contrasté et porte accessibilityState.selected).
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  testID,
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (v: T) => void;
  testID?: string;
}) {
  return (
    <View style={styles.track} testID={testID} accessibilityRole="tablist">
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <TouchableOpacity
            key={opt.value}
            style={[styles.segment, active && styles.segmentActive]}
            onPress={() => onChange(opt.value)}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={opt.label}
            testID={`${testID ?? 'segment'}-${opt.value}`}
            activeOpacity={0.8}
          >
            <Text style={[styles.label, active && styles.labelActive]}>{opt.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    flexDirection: 'row',
    backgroundColor: colors.bg,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 4,
    gap: 4,
  },
  segment: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  segmentActive: {
    backgroundColor: colors.primary,
  },
  label: {
    color: colors.textMuted,
    fontSize: font.size.sm,
    fontWeight: '600',
  },
  labelActive: {
    color: colors.text,
    fontWeight: '700',
  },
});
