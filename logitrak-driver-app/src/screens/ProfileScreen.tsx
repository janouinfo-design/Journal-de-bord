import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { colors, spacing, radius, font } from '@/theme/colors';
import { getMyProfile, MyProfile } from '@/api/ble';
import { useAuthStore } from '@/store/authStore';
import { formatDate, formatTime } from '@/utils/trip';
import type { RootStackParamList } from '@/navigation/RootNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function ProfileScreen() {
  const nav = useNavigation<Nav>();
  const { user, signOut } = useAuthStore();
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const p = await getMyProfile();
      setProfile(p);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Profil indisponible. Vérifiez votre connexion.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} size="large" />
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text} />
        }
        testID="profile-scroll"
      >
        {/* Avatar + nom */}
        <View style={styles.headerCard}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>
              {(profile?.name || user?.full_name || user?.email || '?').slice(0, 1).toUpperCase()}
            </Text>
          </View>
          <Text style={styles.name} testID="profile-name">
            {profile?.name || user?.full_name || 'Chauffeur'}
          </Text>
          <Text style={styles.email}>{profile?.email || user?.email}</Text>
        </View>

        {error ? (
          <View style={styles.errorBox} testID="profile-error">
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        {/* Compte */}
        <Section title="Compte">
          <Row
            label="Statut du compte"
            value={profile?.account_active ? 'Actif' : 'Inactif'}
            valueColor={profile?.account_active ? colors.success : colors.danger}
          />
          <Row
            label="Accès mobile"
            value={profile?.driver_active === false ? 'Désactivé' : 'Activé'}
          />
        </Section>

        {/* Identification BLE — état réel, jamais "validé" si non confirmé */}
        <Section title="Identification BLE">
          <Row
            label="Tag BLE associé"
            value={profile?.ble_tag_associated ? 'Oui' : 'Non'}
            valueColor={profile?.ble_tag_associated ? colors.success : colors.textMuted}
          />
          <Row
            label="Dernière détection"
            value={
              profile?.last_ble_detection
                ? `${formatDate(profile.last_ble_detection)} · ${formatTime(profile.last_ble_detection)}`
                : 'Aucune'
            }
          />
        </Section>

        {/* Actions */}
        <TouchableOpacity
          style={styles.actionBtn}
          onPress={() => nav.navigate('ChangePassword')}
          testID="profile-change-password"
        >
          <Text style={styles.actionText}>Changer mon mot de passe</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.actionBtn, styles.logoutBtn]}
          onPress={signOut}
          testID="profile-logout"
        >
          <Text style={[styles.actionText, { color: colors.danger }]}>Se déconnecter</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function Row({
  label,
  value,
  valueColor,
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={[styles.rowValue, valueColor ? { color: valueColor } : null]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  scroll: { padding: spacing.lg },
  headerCard: { alignItems: 'center', marginBottom: spacing.lg },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
  },
  avatarText: { color: colors.text, fontSize: font.size.hero, fontWeight: '700' },
  name: { color: colors.text, fontSize: font.size.xl, fontWeight: '700' },
  email: { color: colors.textMuted, fontSize: font.size.sm, marginTop: 2 },
  errorBox: {
    backgroundColor: 'rgba(239,68,68,0.12)',
    borderColor: colors.danger,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  errorText: { color: colors.danger, fontSize: font.size.sm },
  section: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    color: colors.textMuted,
    fontSize: font.size.xs,
    textTransform: 'uppercase',
    letterSpacing: 1,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: spacing.xs },
  rowLabel: { color: colors.textMuted, fontSize: font.size.sm },
  rowValue: { color: colors.text, fontSize: font.size.sm, fontWeight: '500' },
  actionBtn: {
    backgroundColor: colors.bgCard,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: spacing.md,
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  actionText: { color: colors.primary, fontSize: font.size.md, fontWeight: '600' },
  logoutBtn: { borderColor: 'rgba(239,68,68,0.4)' },
});
