import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { logger } from '@/utils/logger';
import { postDetections, BleDetection } from '@/api/ble';

const QUEUE_KEY = 'logitrak.ble.queue.v1';
const MAX_QUEUE_AGE_MS = 24 * 60 * 60 * 1000; // 24h
const MAX_QUEUE_SIZE = 5_000;

export type QueuedDetection = BleDetection & { _enqueuedAt: number };

async function readQueue(): Promise<QueuedDetection[]> {
  const raw = await AsyncStorage.getItem(QUEUE_KEY);
  if (!raw) return [];
  try {
    return JSON.parse(raw) as QueuedDetection[];
  } catch {
    return [];
  }
}

async function writeQueue(items: QueuedDetection[]) {
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(items));
}

export async function enqueue(d: BleDetection) {
  const queue = await readQueue();
  queue.push({ ...d, _enqueuedAt: Date.now() });
  // Drop oldest if oversize.
  while (queue.length > MAX_QUEUE_SIZE) queue.shift();
  await writeQueue(queue);
  logger.debug('queue', 'enqueued detection', { size: queue.length, id: d.identifier });
}

export async function getQueueSize(): Promise<number> {
  const q = await readQueue();
  return q.length;
}

export async function clearQueue() {
  await AsyncStorage.removeItem(QUEUE_KEY);
}

/**
 * Flush the queue to the backend with exponential backoff.
 * Returns the number of detections successfully sent.
 */
export async function flushQueue(): Promise<number> {
  const net = await NetInfo.fetch();
  if (!net.isConnected || !net.isInternetReachable) {
    logger.debug('queue', 'offline; skip flush');
    return 0;
  }

  const queue = await readQueue();
  if (!queue.length) return 0;

  // Drop stale entries.
  const now = Date.now();
  const fresh = queue.filter((q) => now - q._enqueuedAt < MAX_QUEUE_AGE_MS);
  if (fresh.length !== queue.length) {
    logger.warn('queue', `dropped ${queue.length - fresh.length} stale detections`);
  }

  if (!fresh.length) {
    await clearQueue();
    return 0;
  }

  const batchSize = 100;
  let totalSent = 0;
  let remaining = [...fresh];
  let backoff = 1000;

  while (remaining.length) {
    const batch = remaining.slice(0, batchSize);
    try {
      const payload: BleDetection[] = batch.map(({ _enqueuedAt, ...rest }) => rest);
      await postDetections(payload);
      totalSent += batch.length;
      remaining = remaining.slice(batch.length);
      backoff = 1000;
    } catch (e) {
      logger.warn('queue', `flush batch failed; retry in ${backoff}ms`, e);
      await writeQueue(remaining);
      await new Promise((r) => setTimeout(r, backoff));
      backoff = Math.min(backoff * 2, 60_000);
      // Stop after one failed retry to avoid blocking the foreground thread.
      return totalSent;
    }
  }

  await clearQueue();
  logger.info('queue', `flushed ${totalSent} detections`);
  return totalSent;
}
