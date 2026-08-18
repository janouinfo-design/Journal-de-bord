import { create } from 'zustand';
import { getQueueSize, flushQueue } from '@/ble/queue';

type QueueState = {
  size: number;
  flushing: boolean;
  refreshSize: () => Promise<void>;
  triggerFlush: () => Promise<number>;
};

export const useQueueStore = create<QueueState>((set, get) => ({
  size: 0,
  flushing: false,

  refreshSize: async () => {
    const s = await getQueueSize();
    set({ size: s });
  },

  triggerFlush: async () => {
    if (get().flushing) return 0;
    set({ flushing: true });
    const sent = await flushQueue();
    set({ flushing: false });
    await get().refreshSize();
    return sent;
  },
}));
