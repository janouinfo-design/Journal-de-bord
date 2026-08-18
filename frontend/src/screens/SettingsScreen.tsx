import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Switch,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Constants from 'expo-constants';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';
import { colors, spacing, radius, font } from '@/theme/colors';
import { showConfirm } from '@/utils/alert';
import { bleScanner } from '@/ble/scanner';
import {
  getNotificationCatalog,
  getNotificationPreferences,
  updateNotificationPreferences,
  CatalogEvent,
  NotificationPreferences,
} from '@/api/notifications';
import type { RootStackParamList } from '@/navigation/RootNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function SettingsScreen() {
  const nav = useNavigation<Nav>();
  const { signOut } = useAuthStore();
  const { bleEnabled, setBleEnabled } = useSessionStore();

  const [catalog, setCatalog] = useState<CatalogEvent[]>([]);
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [prefsLoading, setPrefsLoading] = useState(true);
  const [savingEvent, setSavingEvent] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [cat, pr] = await Promise.all([
          getNotificationCatalog(),
          getNotificationPreferences(),
        ]);
        // On n'affiche que les événements destinés au chauffeur si l'audience est fournie.
        setCatalog(cat.filter((c) => !c.audience || c.audience === 'driver' || c.audience === 'all'));
        setPrefs(pr);
      } catch {
        // Pas de blocage : si indisponible, on n'affiche pas la section prefs.
        setCatalog([]);
      } finally {
        setPrefsLoading(false);
      }
    })();
  }, []);

  const togglePush = useCallback(
    async (eventKey: string, value: boolean) => {
      if (!prefs) return;
      const prev = prefs;
      const nextEvents = {
        ...prefs.events,
        [eventKey]: { ...(prefs.events[eventKey] || { push: false, email: false, sms: false }), push: value },
      };
      setPrefs({ ...prefs, events: nextEvents });
      setSavingEvent(eventKey);
      try {
        const saved = await updateNotificationPreferences({ events: nextEvents });
        setPrefs(saved);
      } catch {
        setPrefs(prev); // rollback si échec serveur
        showConfirm('Erreur', "La préférence n'a pas pu être enregistrée.");
      } finally {
        setSavingEvent(null);
      }
    },
    [prefs],
  );

  const toggleBle = async (v: boolean) => {
    setBleEnabled(v);
    if (v) await bleScanner.start();
    else await bleScanner.stop();
  };

  const onLogout = () => {
    showConfirm('Se déconnecter', 'Confirmer la déconnexion ?', [
      { text: 'Annuler', style: 'cancel' },
      { text: 'Déconnexion', style: 'destructive', onPress: () => signOut() },
    ]);
  };

  const isDev = __DEV__ === true || Constants.expoConfig?.extra?.env === 'development';

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView contentContainerStyle={styles.scroll} testID="settings-scroll">
        {/* Compte */}
        <Section title="Compte">
          <TouchableOpacity
            style={styles.rowBtn}
            onPress={() => nav.navigate('ChangePassword')}
            testID="settings-change-password"
          >
            <Text style={styles.rowBtnText}>Changer mon mot de passe</Text>
            <Text style={styles.chevron}>›</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.rowBtn} onPress={onLogout} testID="settings-logout">
            <Text style={[styles.rowBtnText, { color: colors.danger }]}>Se déconnecter</Text>
            <Text style={styles.chevron}>›</Text>
          </TouchableOpacity>
        </Section>

        {/* Bluetooth (contrôle chauffeur réel) */}
        <Section title="Bluetooth">
          <View style={styles.rowToggle}>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowLabel}>Détection automatique BLE</Text>
              <Text style={styles.rowSub}>Active le scan en avant-plan (build natif)</Text>
            </View>
            <Switch
              value={bleEnabled}
              onValueChange={toggleBle}
              trackColor={{ true: colors.primary, false: colors.border }}
              thumbColor={colors.text}
              testID="settings-ble-toggle"
            />
          </View>
        </Section>

        {/* Notifications — préférences RÉELLES du chauffeur */}
        <Section title="Notifications">
          {prefsLoading ? (
            <ActivityIndicator color={colors.primary} style={{ paddingVertical: spacing.md }} />
          ) : catalog.length === 0 || !prefs ? (
            <Text style={styles.rowSub} testID="settings-notif-empty">
              Aucune préférence de notification disponible.
            </Text>
          ) : (
            catalog.map((ev) => {
              const ch = prefs.events[ev.event] || ev.default_channels;
              return (
                <View style={styles.rowToggle} key={ev.event}>
                  <View style={{ flex: 1, paddingRight: spacing.md }}>
                    <Text style={styles.rowLabel}>{ev.label}</Text>
                    <Text style={styles.rowSub}>Notification push</Text>
                  </View>
                  <Switch
                    value={Boolean(ch?.push)}
                    disabled={savingEvent === ev.event}
                    onValueChange={(v) => togglePush(ev.event, v)}
                    trackColor={{ true: colors.primary, false: colors.border }}
                    thumbColor={colors.text}
                    testID={`settings-notif-${ev.event}`}
                  />
                </View>
              );
            })
          )}
        </Section>

        {/* Application — jamais d'URL/secret */}
        <Section title="Application">
          <Row label="Version" value={String(Constants.expoConfig?.version || '0.1.0')} />
          {isDev ? <Row label="Environnement" value="développement" /> : null}
        </Section>

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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue} numberOfLines={1}>
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
  rowBtn: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  rowBtnText: { color: colors.primary, fontSize: font.size.md, fontWeight: '500' },
  chevron: { color: colors.textMuted, fontSize: font.size.lg },
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
  legal: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    textAlign: 'center',
    marginTop: spacing.lg,
    lineHeight: 16,
  },
});
