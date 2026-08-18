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
import { useNavigation } from '@react-navigation/native';
import { showConfirm } from '@/utils/alert';
import { colors, spacing, radius, font } from '@/theme/colors';
import { changePassword } from '@/api/client';
import { useAuthStore } from '@/store/authStore';

/**
 * Écran de changement de mot de passe forcé (must_change_password = true).
 * Tant que le mot de passe n'est pas changé, l'utilisateur ne peut PAS accéder à l'app
 * (le RootNavigator n'affiche que cet écran). Utilise l'endpoint réel /auth/change-password.
 */
export function ChangePasswordScreen() {
  const { clearMustChangePassword, signOut, mustChangePassword } = useAuthStore();
  const nav = useNavigation<any>();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async () => {
    setError(null);
    if (next.length < 8) {
      setError('Le nouveau mot de passe doit contenir au moins 8 caractères.');
      return;
    }
    if (next !== confirm) {
      setError('Les deux mots de passe ne correspondent pas.');
      return;
    }
    setLoading(true);
    try {
      await changePassword(current, next);
      clearMustChangePassword();
      // Accès non forcé (depuis Profil/Réglages) : revenir en arrière après succès.
      if (!mustChangePassword && nav.canGoBack?.()) {
        nav.goBack();
      } else {
        showConfirm('Mot de passe modifié', 'Vous pouvez maintenant utiliser l’application.');
      }
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Impossible de changer le mot de passe.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.header}>
          <Text style={styles.title}>Nouveau mot de passe requis</Text>
          <Text style={styles.subtitle}>
            Pour votre sécurité, vous devez choisir un nouveau mot de passe avant de continuer.
          </Text>
        </View>

        <View style={styles.form}>
          <Text style={styles.label}>Mot de passe actuel (temporaire)</Text>
          <TextInput
            style={styles.input}
            value={current}
            onChangeText={setCurrent}
            secureTextEntry
            placeholder="••••••••"
            placeholderTextColor={colors.textMuted}
            testID="pwd-current"
          />

          <Text style={styles.label}>Nouveau mot de passe (min. 8 caractères)</Text>
          <TextInput
            style={styles.input}
            value={next}
            onChangeText={setNext}
            secureTextEntry
            placeholder="••••••••"
            placeholderTextColor={colors.textMuted}
            testID="pwd-new"
          />

          <Text style={styles.label}>Confirmer le nouveau mot de passe</Text>
          <TextInput
            style={styles.input}
            value={confirm}
            onChangeText={setConfirm}
            secureTextEntry
            placeholder="••••••••"
            placeholderTextColor={colors.textMuted}
            testID="pwd-confirm"
          />

          {error ? (
            <Text style={styles.error} testID="pwd-error">
              {error}
            </Text>
          ) : null}

          <TouchableOpacity
            onPress={onSubmit}
            disabled={loading}
            style={[styles.submit, loading && { opacity: 0.6 }]}
            testID="pwd-submit"
          >
            {loading ? (
              <ActivityIndicator color={colors.text} />
            ) : (
              <Text style={styles.submitText}>Valider</Text>
            )}
          </TouchableOpacity>

          <TouchableOpacity onPress={signOut} style={styles.logout} testID="pwd-logout">
            <Text style={styles.logoutText}>Se déconnecter</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, paddingHorizontal: spacing.lg },
  header: { paddingTop: spacing.xxl, marginBottom: spacing.lg },
  title: { color: colors.text, fontSize: font.size.xxl, fontWeight: '700' },
  subtitle: { color: colors.textMuted, fontSize: font.size.md, marginTop: spacing.sm, lineHeight: 20 },
  form: { flex: 1 },
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
  error: { color: colors.danger, marginTop: spacing.md, fontSize: font.size.sm, textAlign: 'center' },
  submit: {
    marginTop: spacing.lg,
    backgroundColor: colors.primary,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    alignItems: 'center',
  },
  submitText: { color: colors.text, fontSize: font.size.lg, fontWeight: '600' },
  logout: { marginTop: spacing.lg, alignItems: 'center' },
  logoutText: { color: colors.textMuted, fontSize: font.size.sm },
});
