import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { colors, spacing, radius, font } from '../theme/theme';
import { useAuth } from '../context/AuthContext';
import { useDriverConsole } from '../hooks/useDriverConsole';
import { Card, SectionTitle, Pill } from '../components/ui';
import Button from '../components/Button';
import DetectedVehicleCard from '../components/DetectedVehicleCard';
import FleetTagRow from '../components/FleetTagRow';
import ModeSelector from '../components/ModeSelector';
import { tagLabel } from '../services/detection';

export default function ConsoleScreen() {
  const { user, signOut } = useAuth();
  const c = useDriverConsole();
  const [toast, setToast] = useState(null);

  const showToast = (message, kind = 'info') => {
    setToast({ message, kind });
    setTimeout(() => setToast(null), 3000);
  };

  const onSelectMode = async (m) => {
    const res = await c.changeMode(m);
    if (res.ok) showToast(`Mode ${m === 'pro' ? 'PRO' : 'PRIVÉ'} activé`, 'success');
    else showToast(res.message || 'Bascule impossible', 'error');
  };

  const onTestTag = async (tag) => {
    const res = await c.testTag(tag);
    if (res.ok) showToast(`Test envoyé : ${tagLabel(tag)}`, 'success');
    else showToast(res.message || 'Test échoué', 'error');
  };

  const tagKeyOf = (tag) =>
    String(tag.mac || tag.uuid || tag.ble_id || tag.bleId || tag.id || tagLabel(tag));

  if (c.loading) {
    return (
      <SafeAreaView style={styles.safe}>
        <StatusBar style="light" />
        <View style={styles.center}>
          <ActivityIndicator color={colors.primary} size="large" />
          <Text style={styles.loadingText}>Chargement de la console…</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <StatusBar style="light" />

      {/* En-tête */}
      <View style={styles.header}>
        <View>
          <Text style={styles.headerTitle}>Console Chauffeur</Text>
          <Text style={styles.headerSub} numberOfLines={1}>
            {user?.name || user?.email || 'Chauffeur'}
            {user?.company ? ` · ${user.company}` : ''}
          </Text>
        </View>
        <Pressable testID="logout-button" onPress={signOut} style={styles.logoutBtn}>
          <Text style={styles.logoutText}>Déconnexion</Text>
        </Pressable>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={c.refreshing}
            onRefresh={c.refresh}
            tintColor={colors.primary}
          />
        }
      >
        {c.error ? (
          <Card style={styles.errorCard} testID="console-error">
            <Text style={styles.errorTitle}>Erreur de chargement</Text>
            <Text style={styles.errorText}>{c.error}</Text>
            <Button title="Réessayer" variant="outline" onPress={c.refresh} style={{ marginTop: spacing.md }} />
          </Card>
        ) : null}

        {/* Bandeau de scan */}
        <Card style={styles.scanCard}>
          <View style={styles.scanRow}>
            <View style={styles.scanStatus}>
              <View
                style={[
                  styles.scanDot,
                  { backgroundColor: c.scanning ? colors.success : colors.textFaint },
                ]}
              />
              <Text style={styles.scanLabel}>
                {c.bleAvailable
                  ? c.scanning
                    ? 'Scan BLE actif'
                    : 'Scan BLE en pause'
                  : 'BLE indisponible'}
              </Text>
            </View>
            {c.bleAvailable ? (
              <Button
                testID="scan-toggle"
                title={c.scanning ? 'Arrêter' : 'Démarrer le scan'}
                variant={c.scanning ? 'outline' : 'solid'}
                color={c.scanning ? colors.danger : colors.primary}
                onPress={c.scanning ? c.stopScan : c.startScan}
                style={styles.scanBtn}
              />
            ) : null}
          </View>
          {c.bleError ? <Text style={styles.bleError}>{c.bleError}</Text> : null}
        </Card>

        {/* Véhicule détecté */}
        <DetectedVehicleCard
          candidate={c.candidate}
          scanning={c.scanning}
          bleAvailable={c.bleAvailable}
          unavailableReason={c.unavailableReason}
        />

        {/* Mode PRO / PRIVÉ */}
        <Card style={styles.block}>
          <SectionTitle
            right={
              c.mode ? (
                <Pill
                  label={c.mode === 'pro' ? 'PRO' : 'PRIVÉ'}
                  color={c.mode === 'pro' ? colors.pro : colors.prive}
                  bg={c.mode === 'pro' ? colors.proSoft : colors.priveSoft}
                  testID="current-mode-pill"
                />
              ) : (
                <Pill label="Non défini" />
              )
            }
          >
            Type de trajet
          </SectionTitle>
          <ModeSelector current={c.mode} onSelect={onSelectMode} submitting={c.modeSubmitting} />
        </Card>

        {/* Tags BLE de la flotte */}
        <Card style={styles.block}>
          <SectionTitle
            right={<Pill label={`${c.fleetTags.length} tag${c.fleetTags.length > 1 ? 's' : ''}`} />}
          >
            Balises BLE de la flotte
          </SectionTitle>

          {c.fleetTags.length === 0 ? (
            <View style={styles.emptyTags}>
              <Text style={styles.emptyTagsText}>
                Aucune balise BLE n'est configurée pour votre flotte, ou les données sont
                indisponibles.
              </Text>
            </View>
          ) : (
            c.fleetTags.map((tag, i) => {
              const key = tagKeyOf(tag);
              return (
                <FleetTagRow
                  key={key + i}
                  index={i}
                  tag={tag}
                  live={c.liveByTag.get(key)}
                  testing={c.testingTagKey === key}
                  onTest={onTestTag}
                />
              );
            })
          )}
        </Card>

        <Text style={styles.footer}>
          Logitrak Chauffeur · données en temps réel issues de votre flotte
        </Text>
      </ScrollView>

      {toast ? (
        <View
          style={[
            styles.toast,
            toast.kind === 'success' && { borderColor: colors.success },
            toast.kind === 'error' && { borderColor: colors.danger },
          ]}
          testID="toast"
        >
          <Text style={styles.toastText}>{toast.message}</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  loadingText: { color: colors.textMuted, fontSize: font.size.md },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: { color: colors.text, fontSize: font.size.lg, fontWeight: font.weight.bold },
  headerSub: { color: colors.textMuted, fontSize: font.size.xs, marginTop: 2, maxWidth: 240 },
  logoutBtn: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  logoutText: { color: colors.textMuted, fontSize: font.size.sm },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xxl },
  scanCard: { marginBottom: spacing.lg, padding: spacing.md },
  scanRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  scanStatus: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  scanDot: { width: 10, height: 10, borderRadius: 5 },
  scanLabel: { color: colors.text, fontSize: font.size.md, fontWeight: font.weight.medium },
  scanBtn: { height: 40, paddingHorizontal: spacing.md },
  bleError: { color: colors.warning, fontSize: font.size.sm, marginTop: spacing.sm },
  block: { marginBottom: spacing.lg },
  emptyTags: { paddingVertical: spacing.lg },
  emptyTagsText: { color: colors.textMuted, fontSize: font.size.sm, textAlign: 'center' },
  errorCard: {
    marginBottom: spacing.lg,
    borderColor: colors.danger,
    backgroundColor: colors.dangerSoft,
  },
  errorTitle: { color: colors.danger, fontSize: font.size.md, fontWeight: font.weight.semibold },
  errorText: { color: colors.text, fontSize: font.size.sm, marginTop: spacing.xs },
  footer: {
    color: colors.textFaint,
    fontSize: font.size.xs,
    textAlign: 'center',
    marginTop: spacing.md,
  },
  toast: {
    position: 'absolute',
    left: spacing.lg,
    right: spacing.lg,
    bottom: spacing.xl,
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
  },
  toastText: { color: colors.text, fontSize: font.size.sm, textAlign: 'center' },
});
