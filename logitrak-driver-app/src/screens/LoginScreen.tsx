import React, { useState, useEffect } from 'react';
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
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuthStore } from '@/store/authStore';
import { colors, spacing, radius, font } from '@/theme/colors';

const REMEMBER_KEY = 'logitrak.remember_email';

export function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const { signIn, loading, error } = useAuthStore();

  // Au montage : recharge l'e-mail mémorisé (si "Rester connecté" était coché).
  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(REMEMBER_KEY);
        if (saved) {
          setEmail(saved);
          setRemember(true);
        }
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const onSubmit = async () => {
    // Trim sur les DEUX champs : évite les espaces parasites du clavier mobile.
    const cleanEmail = email.trim().toLowerCase();
    const cleanPassword = password.trim();
    if (!cleanEmail || !cleanPassword) return;

    // Mémorise (ou efface) l'e-mail selon la case cochée. Le mot de passe n'est JAMAIS stocké.
    try {
      if (remember) {
        await AsyncStorage.setItem(REMEMBER_KEY, cleanEmail);
      } else {
        await AsyncStorage.removeItem(REMEMBER_KEY);
      }
    } catch {
      /* ignore */
    }

    await signIn(cleanEmail, cleanPassword);
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
            textContentType="username"
            testID="login-email"
          />

          <Text style={styles.label}>Mot de passe</Text>
          <View style={styles.passwordRow}>
            <TextInput
              style={styles.passwordInput}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••••"
              placeholderTextColor={colors.textMuted}
              secureTextEntry={!showPassword}
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="off"
              textContentType="password"
              onSubmitEditing={onSubmit}
              testID="login-password"
            />
            <TouchableOpacity
              style={styles.eyeBtn}
              onPress={() => setShowPassword((v) => !v)}
              testID="login-toggle-password"
              accessibilityLabel={showPassword ? 'Masquer le mot de passe' : 'Afficher le mot de passe'}
            >
              <Text style={styles.eyeText}>{showPassword ? '🙈' : '👁️'}</Text>
            </TouchableOpacity>
          </View>

          {/* Case "Rester connecté" */}
          <TouchableOpacity
            style={styles.rememberRow}
            onPress={() => setRemember((v) => !v)}
            testID="login-remember"
            activeOpacity={0.7}
          >
            <View style={[styles.checkbox, remember && styles.checkboxChecked]}>
              {remember ? <Text style={styles.checkmark}>✓</Text> : null}
            </View>
            <Text style={styles.rememberText}>Rester connecté</Text>
          </TouchableOpacity>

          {error ? (
            <Text style={styles.error} testID="login-error">
              {error}
            </Text>
          ) : null}

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
  passwordRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  passwordInput: {
    flex: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: colors.text,
    fontSize: font.size.md,
  },
  eyeBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  eyeText: { fontSize: font.size.lg },
  rememberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: spacing.md,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: radius.sm,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  checkboxChecked: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  checkmark: { color: colors.text, fontSize: font.size.sm, fontWeight: '700' },
  rememberText: { color: colors.text, fontSize: font.size.md },
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
