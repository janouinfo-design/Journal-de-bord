import { apiClient } from './client';

/**
 * Préférences de notifications (contrats RÉELS, accessibles au chauffeur) :
 * - GET  /api/livre/notifications/catalog       -> { events: CatalogEvent[] }
 * - GET  /api/livre/notifications/preferences   -> { user_id, channels, events }
 * - PUT  /api/livre/notifications/preferences   -> préférences mises à jour
 */

export type Channels = { push: boolean; email: boolean; sms: boolean };

export type CatalogEvent = {
  event: string;
  label: string;
  default_channels: Channels;
  audience?: string;
};

export type NotificationPreferences = {
  user_id?: string;
  channels?: Channels;
  events: Record<string, Channels>;
};

export async function getNotificationCatalog(): Promise<CatalogEvent[]> {
  const { data } = await apiClient.get('/api/livre/notifications/catalog');
  return Array.isArray(data?.events) ? data.events : [];
}

export async function getNotificationPreferences(): Promise<NotificationPreferences> {
  const { data } = await apiClient.get('/api/livre/notifications/preferences');
  return { user_id: data?.user_id, channels: data?.channels, events: data?.events || {} };
}

export async function updateNotificationPreferences(
  prefs: Partial<NotificationPreferences>,
): Promise<NotificationPreferences> {
  const { data } = await apiClient.put('/api/livre/notifications/preferences', prefs);
  return { user_id: data?.user_id, channels: data?.channels, events: data?.events || {} };
}
