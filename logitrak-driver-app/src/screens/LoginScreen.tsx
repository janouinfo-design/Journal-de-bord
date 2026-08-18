import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuthStore } from '@/store/authStore';
import { colors, spacing, radius, font } from '@/theme/colors';

export function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { signIn, loading, error } = useAuthStore();

  const onSubmit = async () => {
    if (!email || !password) return;
    await signIn(email.trim(), password);
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.brandBlock}>
          <View style={styles.logoCircle}>
            <Text style={styles.logoText}>L</Text>
          </View>
          <Text style={styles.brand}>LOGITRAK</Text>
          <Text style={styles.tagline}>Console Chauffeur</Text>
        </View>

        <View style={styles.form}>
          <Text style={styles.label}>E-mail</Text>
          <TextInput
            style={styles.input}
            value={email}
            onChangeText={setEmail}
            placeholder="chauffeur@logitrak.ch"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            testID="login-email"
          />

          <Text style={styles.label}>Mot de passe</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            placeholder="••••••••"
            placeholderTextColor={colors.textMuted}
            secureTextEntry
            testID="login-password"
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <TouchableOpacity
            onPress={onSubmit}
            disabled={loading}
            style={[styles.submit, loading && { opacity: 0.6 }]}
            testID="login-submit"
          >
            {loading ? (
              <ActivityIndicator color={colors.text} />
            ) : (
              <Text style={styles.submitText}>Se connecter</Text>
            )}
          </TouchableOpacity>
        </View>

        <Text style={styles.legal}>
          Identification automatique via tag Bluetooth.{'\n'}
          Le mode PRIVÉ masque entièrement vos trajets personnels.
        </Text>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, paddingHorizontal: spacing.lg },
  brandBlock: {
    flex: 1.2,
    alignItems: 'center',
    justifyContent: 'center',
    paddingTop: spacing.xxl,
  },
  logoCircle: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
  },
  logoText: { color: colors.text, fontSize: font.size.hero, fontWeight: '700' },
  brand: {
    color: colors.text,
    fontSize: font.size.xxl,
    fontWeight: '700',
    letterSpacing: 4,
  },
  tagline: { color: colors.textMuted, fontSize: font.size.md, marginTop: spacing.xs },
  form: { flex: 1.5, justifyContent: 'flex-start' },
  label: {
    color: colors.textMuted,
    fontSize: font.size.sm,
    marginBottom: spacing.xs,
    marginTop: spacing.md,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  input: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: colors.text,
    fontSize: font.size.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  error: {
    color: colors.danger,
    marginTop: spacing.md,
    fontSize: font.size.sm,
    textAlign: 'center',
  },
  submit: {
    marginTop: spacing.lg,
    backgroundColor: colors.primary,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    alignItems: 'center',
  },
  submitText: {
    color: colors.text,
    fontSize: font.size.lg,
    fontWeight: '600',
  },
  legal: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    textAlign: 'center',
    paddingBottom: spacing.lg,
    lineHeight: 16,
  },
});
