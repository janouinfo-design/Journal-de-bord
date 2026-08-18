import { Alert, AlertButton, Platform } from 'react-native';

/**
 * Boîte de dialogue multiplateforme.
 * - Natif (iOS/Android) : utilise le vrai Alert.alert (cible de production).
 * - Web (preview) : React Native Web n'implémente pas Alert.alert avec boutons,
 *   on retombe donc sur window.confirm / window.alert pour conserver le flux.
 *
 * Aucune logique métier ici : simple adaptation de présentation par plateforme.
 */
export function showConfirm(
  title: string,
  message?: string,
  buttons: AlertButton[] = [{ text: 'OK' }],
): void {
  if (Platform.OS === 'web') {
    const text = [title, message].filter(Boolean).join('\n\n');
    const cancelBtn = buttons.find((b) => b.style === 'cancel');
    const actionBtn = buttons.find((b) => b.style !== 'cancel');
    // Si un seul bouton non-cancel : simple information.
    if (buttons.length <= 1) {
      // eslint-disable-next-line no-alert
      window.alert(text);
      buttons[0]?.onPress?.();
      return;
    }
    // eslint-disable-next-line no-alert
    const ok = window.confirm(text);
    if (ok) actionBtn?.onPress?.();
    else cancelBtn?.onPress?.();
    return;
  }
  Alert.alert(title, message, buttons);
}
