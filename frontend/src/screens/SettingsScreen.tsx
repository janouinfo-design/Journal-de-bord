import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Switch,
  TouchableOpacity,
  ScrollView,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Constants from 'expo-constants';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';
import { useQueueStore } from '@/store/queueStore';
import { colors, spacing, radius, font } from '@/theme/colors';
import { getApiUrl } from '@/api/client';
import { bleScanner } from '@/ble/scanner';

export function SettingsScreen() {
  const { user, signOut } = useAuthStore();
  const { bleEnabled, setBleEnabled } = useSessionStore();
  const { size: queueSize, triggerFlush, flushing } = useQueueStore();
  const [scannerLabel, setScannerLabel] = useState('—');

  useEffect(() => {
    const t = setInterval(() => setScannerLabel(bleScanner.getState()), 1000);
    return () => clearInterval(t);
  }, []);

  const toggleBle = async (v: boolean) => {
    setBleEnabled(v);
    if (v) {
      await bleScanner.start();
    } else {
      await bleScanner.stop();
    }
  };

  const onLogout = () => {
    Alert.alert('Se déconnecter', 'Confirmer la déconnexion ?', [
      { text: 'Annuler', style: 'cancel' },
      {
        text: 'Déconnexion',
        style: 'destructive',
        onPress: () => {
          signOut();
        },
      },
    ]);
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Section title="Compte">
          <Row label="Identité" value={user?.full_name || user?.email || '—'} />
          <Row label="Rôle" value={user?.role || '—'} />
        </Section>

        <Section title="Bluetooth">
          <View style={styles.rowToggle}>
            <View>
              <Text style={styles.rowLabel}>Détection automatique BLE</Text>
              <Text style={styles.rowSub}>Active le scan en avant-plan</Text>
            </View>
            <Switch
              value={bleEnabled}
              onValueChange={toggleBle}
              trackColor={{ true: colors.primary, false: colors.border }}
              thumbColor={colors.text}
              testID="settings-ble-toggle"
            />
          </View>
          <Row label="État scanner" value={scannerLabel} />
          <Row label="File hors-ligne" value={`${queueSize} détection(s)`} />
          <TouchableOpacity
            onPress={triggerFlush}
            disabled={flushing || queueSize === 0}
            style={[styles.btnSecondary, (flushing || queueSize === 0) && { opacity: 0.5 }]}
            testID="settings-flush"
          >
            <Text style={styles.btnSecondaryText}>
              {flushing ? 'Synchronisation…' : 'Synchroniser maintenant'}
            </Text>
          </TouchableOpacity>
        </Section>

        <Section title="Réseau">
          <Row label="API" value={getApiUrl()} mono />
          <Row label="App version" value={String(Constants.expoConfig?.version || '0.1.0')} />
          <Row
            label="Build"
            value={String(
              Constants.expoConfig?.ios?.buildNumber ||
                Constants.expoConfig?.android?.versionCode ||
                '1',
            )}
          />
        </Section>

        <TouchableOpacity onPress={onLogout} style={styles.btnDanger} testID="settings-logout">
          <Text style={styles.btnDangerText}>Se déconnecter</Text>
        </TouchableOpacity>

        <Text style={styles.legal}>
          © Logitrak 2026 · Données traitées conformément à la nLPD/RGPD.{'\n'}
          Le mode PRIVÉ masque entièrement vos trajets personnels — y compris pour votre manager.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <View style={styles.sectionBody}>{children}</View>
    </View>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, mono ? styles.mono : null]} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  scroll: { padding: spacing.lg },
  section: { marginBottom: spacing.lg },
  sectionTitle: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    letterSpacing: 2,
    textTransform: 'uppercase',
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  sectionBody: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  rowToggle: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  rowLabel: { color: colors.text, fontSize: font.size.sm, fontWeight: '500' },
  rowSub: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2 },
  rowValue: { color: colors.textMuted, fontSize: font.size.sm, maxWidth: '55%' },
  mono: { fontFamily: 'Courier', fontSize: font.size.xs },

  btnSecondary: {
    marginVertical: spacing.md,
    backgroundColor: colors.bgElevated,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    alignItems: 'center',
  },
  btnSecondaryText: { color: colors.text, fontWeight: '500', fontSize: font.size.sm },

  btnDanger: {
    marginTop: spacing.md,
    backgroundColor: colors.danger,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    alignItems: 'center',
  },
  btnDangerText: { color: colors.text, fontWeight: '600', fontSize: font.size.md },

  legal: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    textAlign: 'center',
    marginTop: spacing.lg,
    lineHeight: 16,
  },
});
