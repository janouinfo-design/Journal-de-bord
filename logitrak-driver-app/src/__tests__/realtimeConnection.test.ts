/**
 * WS temps réel : le token ne doit JAMAIS apparaître dans l'URL ; il est transmis
 * via le header Authorization (WebSocket React Native, 3e argument).
 */
jest.mock('@/api/client', () => ({
  getApiUrl: jest.fn(() => 'https://example.test'),
  getAccessToken: jest.fn(),
}));
jest.mock('@/utils/logger', () => ({
  logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

import { buildRealtimeConnection } from '@/hooks/useRealtime';

describe('buildRealtimeConnection', () => {
  const TOKEN = 'secret-token-abc123';

  it('chauffeur : URL sans token + header Authorization Bearer', () => {
    const { url, options } = buildRealtimeConnection('https://journal.example', 'driver', TOKEN);
    expect(url).toBe('wss://journal.example/api/livre/realtime');
    expect(url).not.toContain(TOKEN);
    expect(url).not.toContain('token=');
    expect(options.headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it('admin : chemin ws/admin, mêmes garanties', () => {
    const { url, options } = buildRealtimeConnection('http://10.0.0.5:8001', 'admin', TOKEN);
    expect(url).toBe('wss://10.0.0.5:8001/api/livre/ws/admin');
    expect(url).not.toContain(TOKEN);
    expect(options.headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });
});
