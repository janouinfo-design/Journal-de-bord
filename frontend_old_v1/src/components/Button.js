import React from 'react';
import { Text, StyleSheet, Pressable, ActivityIndicator, View } from 'react-native';
import { colors, radius, spacing, font } from '../theme/theme';

/**
 * Bouton principal réutilisable.
 * variant: 'solid' | 'outline' | 'ghost'
 */
export default function Button({
  title,
  onPress,
  loading = false,
  disabled = false,
  variant = 'solid',
  color = colors.primary,
  textColor,
  icon = null,
  style,
  testID,
}) {
  const isDisabled = disabled || loading;
  const solid = variant === 'solid';
  const outline = variant === 'outline';

  const bg = solid ? color : 'transparent';
  const border = outline ? color : 'transparent';
  const txt = textColor || (solid ? '#04110F' : color);

  return (
    <Pressable
      testID={testID}
      onPress={isDisabled ? undefined : onPress}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, borderColor: border, borderWidth: outline ? 1.5 : 0 },
        pressed && !isDisabled ? styles.pressed : null,
        isDisabled ? styles.disabled : null,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={txt} />
      ) : (
        <View style={styles.content}>
          {icon}
          <Text style={[styles.text, { color: txt }]}>{title}</Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    height: 52,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  content: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  text: { fontSize: font.size.md, fontWeight: font.weight.semibold },
  pressed: { opacity: 0.85 },
  disabled: { opacity: 0.45 },
});
