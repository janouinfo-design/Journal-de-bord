import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import Button from '../components/Button';
import { colors, spacing, radius, font } from '../theme/theme';
import { useAuth } from '../context/AuthContext';
import { ApiError, pingApi, diagnoseLogin } from '../services/api';
import { API_URL } from '../services/config';

export default function LoginScreen() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [diagOpen, setDiagOpen] = useState(false);
  const [diagRunning, setDiagRunning] = useState(false);
  const [diag, setDiag] = useState(null);

  const canSubmit = email.trim().length > 3 && password.length >= 1;

  const onSubmit = async () => {
    setError(null);
    if (!canSubmit) {
      setError('Veuillez saisir votre email et votre mot de passe.');
      return;
    }
    setLoading(true);
    try {
      await signIn(email.trim(), password);
    } catch (e) {
      let msg = e instanceof ApiError ? e.message : 'Connexion impossible.';
      // Enrichissement diagnostique en cas de refus d'identifiants.
      if (e instanceof ApiError && e.status === 401) {
        msg =
          (e.message || 'Identifiants refusés.') +
          '\nVérifiez le mot de passe et que ce compte chauffeur est actif.';
      }
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const runDiagnostic = async () => {
    setDiagRunning(true);
    setDiag(null);
    const ping = await pingApi();
    let loginTest = null;
    if (email.trim() && password) {
      loginTest = await diagnoseLogin(email.trim(), password);
    }
    setDiag({ ping, loginTest });
    setDiagRunning(false);
    setDiagOpen(true);
  };

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.header}>
            <View style={styles.logoBadge}>
              <Text style={styles.logoText}>LT</Text>
            </View>
            <Text style={styles.brand}>Logitrak</Text>
            <Text style={styles.subtitle}>Console Chauffeur</Text>
          </View>

          <View style={styles.form}>
            <Text style={styles.label}>Adresse email</Text>
            <TextInput
              testID="login-email-input"
              style={styles.input}
              placeholder="vous@entreprise.ch"
              placeholderTextColor={colors.textFaint}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              value={email}
              onChangeText={setEmail}
              editable={!loading}
            />

            <Text style={[styles.label, { marginTop: spacing.lg }]}>Mot de passe</Text>
            <View style={styles.passRow}>
              <TextInput
                testID="login-password-input"
                style={[styles.input, styles.passInput]}
                placeholder="••••••••"
                placeholderTextColor={colors.textFaint}
                secureTextEntry={!showPass}
                value={password}
                onChangeText={setPassword}
                editable={!loading}
                onSubmitEditing={onSubmit}
              />
              <Text
                testID="login-toggle-password"
                style={styles.showBtn}
                onPress={() => setShowPass((v) => !v)}
              >
                {showPass ? 'Masquer' : 'Afficher'}
              </Text>
            </View>

            {error ? (
              <View style={styles.errorBox} testID="login-error">
                <Text style={styles.errorText}>{error}</Text>
              </View>
            ) : null}

            <Button
              testID="login-submit"
              title="Se connecter"
              onPress={onSubmit}
              loading={loading}
              disabled={!canSubmit}
              style={{ marginTop: spacing.xl }}
            />

            <Text style={styles.hint}>
              Connexion sécurisée — votre entreprise est reconnue automatiquement.
            </Text>

            <Text
              testID="login-diagnostic-toggle"
              style={styles.diagLink}
              onPress={runDiagnostic}
            >
              {diagRunning ? 'Diagnostic en cours…' : 'Diagnostic de connexion'}
            </Text>

            {diagOpen && diag ? (
              <View style={styles.diagBox} testID="login-diagnostic-box">
                <Text style={styles.diagTitle}>Diagnostic</Text>
                <Text style={styles.diagLine} numberOfLines={2}>
                  Serveur : {diag.ping.url}
                </Text>
                <Text
                  style={[
                    styles.diagLine,
                    { color: diag.ping.reachable ? colors.success : colors.danger },
                  ]}
                >
                  Joignabilité : {diag.ping.reachable ? `OK (HTTP ${diag.ping.status}, ${diag.ping.ms} ms)` : `échec — ${diag.ping.error || 'injoignable'}`}
                </Text>
                {diag.loginTest ? (
                  <>
                    <Text
                      style={[
                        styles.diagLine,
                        { color: diag.loginTest.ok ? colors.success : colors.warning },
                      ]}
                    >
                      Test login : HTTP {diag.loginTest.status} ({diag.loginTest.ms} ms)
                    </Text>
                    <Text style={styles.diagDetail}>
                      Réponse serveur : {diag.loginTest.detail}
                    </Text>
                    {diag.loginTest.status === 401 ? (
                      <Text style={styles.diagAdvice}>
                        → Identifiants refusés par Logitrak. Vérifiez le mot de passe et que ce
                        compte chauffeur est actif.
                      </Text>
                    ) : null}
                  </>
                ) : (
                  <Text style={styles.diagDetail}>
                    Saisissez email + mot de passe pour tester aussi la connexion.
                  </Text>
                )}
              </View>
            ) : null}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: spacing.xl },
  header: { alignItems: 'center', marginBottom: spacing.xxl },
  logoBadge: {
    width: 72,
    height: 72,
    borderRadius: radius.xl,
    backgroundColor: colors.primarySoft,
    borderWidth: 1.5,
    borderColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
  },
  logoText: { color: colors.primary, fontSize: font.size.xxl, fontWeight: font.weight.bold },
  brand: { color: colors.text, fontSize: font.size.xxl, fontWeight: font.weight.bold },
  subtitle: { color: colors.textMuted, fontSize: font.size.md, marginTop: 2 },
  form: {},
  label: {
    color: colors.textMuted,
    fontSize: font.size.sm,
    fontWeight: font.weight.medium,
    marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    height: 52,
    color: colors.text,
    fontSize: font.size.md,
  },
  passRow: { position: 'relative', justifyContent: 'center' },
  passInput: { paddingRight: 84 },
  showBtn: {
    position: 'absolute',
    right: spacing.lg,
    color: colors.primary,
    fontSize: font.size.sm,
    fontWeight: font.weight.semibold,
  },
  errorBox: {
    backgroundColor: colors.dangerSoft,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.lg,
    borderWidth: 1,
    borderColor: colors.danger,
  },
  errorText: { color: colors.danger, fontSize: font.size.sm },
  hint: {
    color: colors.textFaint,
    fontSize: font.size.xs,
    textAlign: 'center',
    marginTop: spacing.lg,
  },
  diagLink: {
    color: colors.primary,
    fontSize: font.size.sm,
    textAlign: 'center',
    marginTop: spacing.md,
    fontWeight: font.weight.medium,
  },
  diagBox: {
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  diagTitle: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    fontWeight: font.weight.semibold,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: spacing.sm,
  },
  diagLine: { color: colors.text, fontSize: font.size.xs, marginBottom: 4 },
  diagDetail: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 4 },
  diagAdvice: { color: colors.warning, fontSize: font.size.xs, marginTop: spacing.sm },
});
