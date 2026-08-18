import Constants from 'expo-constants';

const DEBUG =
  (Constants.expoConfig?.extra as Record<string, unknown> | undefined)?.debug === true ||
  process.env.EXPO_PUBLIC_DEBUG === '1';

type Level = 'debug' | 'info' | 'warn' | 'error';

function ts(): string {
  const d = new Date();
  return `${d.toISOString().slice(11, 23)}`;
}

function emit(level: Level, scope: string, msg: string, extra?: unknown) {
  if (!DEBUG && level === 'debug') return;
  const prefix = `[${ts()}] [${level.toUpperCase()}] [${scope}]`;
  if (extra !== undefined) {
    // eslint-disable-next-line no-console
    console.log(prefix, msg, extra);
  } else {
    // eslint-disable-next-line no-console
    console.log(prefix, msg);
  }
}

export const logger = {
  debug: (scope: string, msg: string, extra?: unknown) => emit('debug', scope, msg, extra),
  info: (scope: string, msg: string, extra?: unknown) => emit('info', scope, msg, extra),
  warn: (scope: string, msg: string, extra?: unknown) => emit('warn', scope, msg, extra),
  error: (scope: string, msg: string, extra?: unknown) => emit('error', scope, msg, extra),
};
