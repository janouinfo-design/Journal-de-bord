import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, Animated, Easing,
} from 'react-native';
import { colors, spacing, radius, font } from '@/theme/colors';
import { showConfirm } from '@/utils/alert';
import { triggerSos } from '@/api/ble';

const HOLD_MS = 2500; // maintien ~2.5 s pour éviter tout déclenchement accidentel

/**
 * Bouton SOS Urgence — anti-erreur double : MAINTIEN (~2.5s) + CONFIRMATION.
 * - Envoie l'alerte au backend (source de vérité). Aucune position calculée localement.
 * - Anti double-envoi (verrou local + dédup backend).
 * - Offline / erreur : message honnête, pas de faux succès.
 * - `isPrivate` : informe le chauffeur que la position pourra être partagée en cas d'urgence.
 */
export default function SosButton({ isPrivate = false, compact = true }: { isPrivate?: boolean; compact?: boolean }) {
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const inFlight = useRef(false);
  const progress = useRef(new Animated.Value(0)).current;
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSend = useCallback(async () => {
    if (inFlight.current) return;   // anti double-envoi
    inFlight.current = true;
    setSending(true);
    setResult(null);
    try {
      const res = await triggerSos();
      if (res.ok) {
        setResult({ ok: true, msg: res.duplicate ? 'Alerte déjà en cours.' : 'Alerte SOS envoyée. Les secours/gestionnaires sont prévenus.' });
      } else {
        setResult({ ok: false, msg: "L'alerte n'a pas pu être envoyée. Réessayez." });
      }
    } catch {
      // offline / timeout : jamais de faux succès
      setResult({ ok: false, msg: 'Connexion indisponible. Alerte NON envoyée — réessayez.' });
    } finally {
      setSending(false);
      inFlight.current = false;
    }
  }, []);

  const confirmAndSend = useCallback(() => {
    const extra = isPrivate
      ? ' En cas d’urgence, votre position pourra être partagée pour permettre l’assistance.'
      : '';
    showConfirm(
      'Déclencher une alerte SOS ?',
      `Une alerte va être envoyée aux gestionnaires.${extra}`,
      [
        { text: 'Annuler', style: 'cancel' },
        { text: 'Envoyer SOS', style: 'destructive', onPress: doSend },
      ],
    );
  }, [doSend, isPrivate]);

  const startHold = useCallback(() => {
    if (sending) return;
    Animated.timing(progress, {
      toValue: 1, duration: HOLD_MS, easing: Easing.linear, useNativeDriver: false,
    }).start();
    holdTimer.current = setTimeout(() => {
      progress.setValue(0);
      confirmAndSend();   // maintien atteint -> confirmation (double garde-fou)
    }, HOLD_MS);
  }, [sending, confirmAndSend, progress]);

  const cancelHold = useCallback(() => {
    if (holdTimer.current) {
      clearTimeout(holdTimer.current);
      holdTimer.current = null;
    }
    Animated.timing(progress, { toValue: 0, duration: 150, useNativeDriver: false }).start();
  }, [progress]);

  const widthInterp = progress.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] });

  // Nettoyage du timer de maintien au démontage (évite fuite/leak).
  useEffect(() => () => { if (holdTimer.current) clearTimeout(holdTimer.current); }, []);

  return (
    <View style={[styles.wrap, compact && styles.wrapCompact]}>
      <Pressable
        onPressIn={startHold}
        onPressOut={cancelHold}
        disabled={sending}
        style={({ pressed }) => [
          styles.btn, compact && styles.btnCompact,
          pressed && styles.btnPressed, sending && styles.btnDisabled,
        ]}
        testID="sos-button"
      >
        {/* jauge de maintien */}
        <Animated.View style={[styles.progress, { width: widthInterp }]} pointerEvents="none" />
        {sending ? (
          <ActivityIndicator color={colors.text} />
        ) : (
          <Text style={[styles.btnText, compact && styles.btnTextCompact]}>SOS</Text>
        )}
      </Pressable>
      <Text style={styles.hint}>Maintenir pour l’urgence</Text>
      {result ? (
        <Text style={[styles.result, { color: result.ok ? colors.success : colors.danger }]} testID="sos-result">
          {result.msg}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: spacing.xl, alignItems: 'center' },
  wrapCompact: { marginTop: spacing.md, alignItems: 'flex-end' },
  btn: {
    width: '100%', backgroundColor: colors.danger, borderRadius: radius.lg,
    paddingVertical: spacing.lg, alignItems: 'center', justifyContent: 'center',
    overflow: 'hidden',
  },
  // Version COMPACTE : petite pastille rouge, toujours clairement identifiable (SOS).
  btnCompact: {
    width: 96, paddingVertical: spacing.sm, borderRadius: radius.pill,
  },
  btnPressed: { opacity: 0.9 },
  btnDisabled: { opacity: 0.6 },
  progress: {
    position: 'absolute', left: 0, top: 0, bottom: 0,
    backgroundColor: '#00000033',
  },
  btnText: { color: colors.text, fontSize: font.size.lg, fontWeight: '700', letterSpacing: 1 },
  btnTextCompact: { fontSize: font.size.md, letterSpacing: 2 },
  hint: { color: colors.textMuted, fontSize: font.size.xs, marginTop: spacing.xs },
  result: { fontSize: font.size.sm, marginTop: spacing.sm, textAlign: 'center' },
});
