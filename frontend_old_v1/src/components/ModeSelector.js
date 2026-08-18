import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { colors, spacing, radius, font } from '../theme/theme';

/**
 * Sélecteur de mode manuel PRO / PRIVÉ.
 * Le mode courant reflète la valeur réelle renvoyée par le serveur (current-session).
 */
export default function ModeSelector({ current, onSelect, submitting }) {
  return (
    <View style={styles.wrap}>
      <ModeButton
        testID="mode-pro"
        label="PRO"
        sub="Trajet professionnel"
        active={current === 'pro'}
        activeColor={colors.pro}
        activeBg={colors.proSoft}
        disabled={submitting}
        onPress={() => onSelect('pro')}
      />
      <ModeButton
        testID="mode-prive"
        label="PRIVÉ"
        sub="Trajet personnel"
        active={current === 'prive'}
        activeColor={colors.prive}
        activeBg={colors.priveSoft}
        disabled={submitting}
        onPress={() => onSelect('prive')}
      />
    </View>
  );
}

function ModeButton({ label, sub, active, activeColor, activeBg, onPress, disabled, testID }) {
  return (
    <Pressable
      testID={testID}
      onPress={disabled ? undefined : onPress}
      style={({ pressed }) => [
        styles.btn,
        {
          borderColor: active ? activeColor : colors.border,
          backgroundColor: active ? activeBg : colors.surface,
        },
        pressed && !disabled ? styles.pressed : null,
        disabled ? styles.disabled : null,
      ]}
    >
      <View style={[styles.indicator, { borderColor: active ? activeColor : colors.borderStrong }]}>
        {active ? <View style={[styles.indicatorDot, { backgroundColor: activeColor }]} /> : null}
      </View>
      <Text style={[styles.label, { color: active ? activeColor : colors.text }]}>{label}</Text>
      <Text style={styles.sub}>{sub}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: 'row', gap: spacing.md },
  btn: {
    flex: 1,
    borderWidth: 1.5,
    borderRadius: radius.lg,
    paddingVertical: spacing.lg,
    alignItems: 'center',
  },
  pressed: { opacity: 0.85 },
  disabled: { opacity: 0.5 },
  indicator: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.sm,
  },
  indicatorDot: { width: 10, height: 10, borderRadius: 5 },
  label: { fontSize: font.size.lg, fontWeight: font.weight.bold, letterSpacing: 1 },
  sub: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
});
