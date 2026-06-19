/* Web Bluetooth scanner hook for the chauffeur PWA.
 *
 * Wraps `navigator.bluetooth.requestLEScan()` (Chrome Android only). On iOS
 * Safari and unsupported browsers, returns `unsupported`.
 *
 * Each discovered advertisement is forwarded to the backend via
 * `POST /api/livre/ble/detections`, debounced to one ingest per identifier
 * every 3 s to avoid flooding.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

const INGEST_DEBOUNCE_MS = 3000;

function detectSupport() {
  if (typeof navigator === "undefined") return "ssr";
  // Web Bluetooth itself
  if (!navigator.bluetooth) return "no-bluetooth";
  // requestLEScan is the experimental scanning API (Chrome Android + flag on desktop)
  if (typeof navigator.bluetooth.requestLEScan !== "function") return "no-scan-api";
  return "ok";
}

export default function useBleScanner() {
  const [support] = useState(detectSupport);
  const [scanning, setScanning] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);
  const [error, setError] = useState(null);
  const scanRef = useRef(null);
  const lastSentRef = useRef(new Map()); // canon -> ts

  const stop = useCallback(() => {
    try { scanRef.current?.stop?.(); } catch (e) { /* ignore */ }
    scanRef.current = null;
    setScanning(false);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (support !== "ok") {
      setError(
        support === "no-bluetooth"
          ? "Web Bluetooth indisponible (iOS Safari ne le supporte pas)."
          : "Le scan BLE n'est pas disponible sur ce navigateur. Utilisez Chrome Android.",
      );
      return false;
    }
    try {
      // Permission gesture
      const scan = await navigator.bluetooth.requestLEScan({
        acceptAllAdvertisements: true,
        keepRepeatedDevices: true,
      });
      scanRef.current = scan;
      setScanning(true);

      const handler = async (event) => {
        const id = (event.device?.name || event.device?.id || "").trim();
        if (!id) return;
        setLastEvent({ id, rssi: event.rssi, ts: Date.now() });
        // Debounce per identifier
        const now = Date.now();
        const prev = lastSentRef.current.get(id) || 0;
        if (now - prev < INGEST_DEBOUNCE_MS) return;
        lastSentRef.current.set(id, now);
        try {
          await api.post("/livre/ble/detections", {
            identifier: id,
            rssi: event.rssi ?? -70,
            platform: "pwa",
            local_name: event.device?.name,
            device_id: event.device?.id,
          });
        } catch (e) {
          // Don't kill the scan on a transient API error
          console.debug("[BLE] ingest failed:", e?.message);
        }
      };
      navigator.bluetooth.addEventListener("advertisementreceived", handler);
      scan.__handler = handler;
      return true;
    } catch (e) {
      setError(e?.message || "Permission refusée");
      setScanning(false);
      return false;
    }
  }, [support]);

  // Clean up listener on unmount
  useEffect(() => {
    return () => {
      const scan = scanRef.current;
      if (scan?.__handler) {
        try { navigator.bluetooth.removeEventListener("advertisementreceived", scan.__handler); }
        catch (e) { /* ignore */ }
      }
      stop();
    };
  }, [stop]);

  return { support, scanning, lastEvent, error, start, stop };
}
