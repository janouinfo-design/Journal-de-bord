import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import {
  Bluetooth, Loader2, Briefcase, User as UserIcon, Smartphone,
  Truck, RefreshCw, Wifi, LogOut, AlertCircle, Tag, Play, Square, RadioTower,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import useBleScanner from "@/hooks/useBleScanner";

function Pulse({ active }) {
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {active && <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 animate-ping" />}
      <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${active ? "bg-emerald-500" : "bg-slate-400"}`} />
    </span>
  );
}

function Confidence({ value }) {
  const v = value ?? 0;
  const color = v >= 75 ? "bg-emerald-400" : v >= 50 ? "bg-amber-400" : "bg-rose-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-full bg-white/20 rounded overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${v}%` }} />
      </div>
      <span className="text-xs font-mono text-white/80 w-8 text-right">{v}</span>
    </div>
  );
}

export default function DriverConsolePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [fleetTags, setFleetTags] = useState([]);
  const [testingTagId, setTestingTagId] = useState(null);
  const scanner = useBleScanner();

  async function loadSession() {
    try {
      const { data } = await api.get("/livre/driver/current-session");
      setSession(data.session);
    } catch (e) {
      // Chauffeur might not be linked to a driver record — that is fine.
      // Anything else (network / 5xx) is logged for debugging.
      if (e?.response?.status && e.response.status !== 400) {
        console.debug("[DriverConsole] current-session fetch failed:", e);
      }
    } finally { setLoading(false); }
  }

  async function loadFleetTags() {
    try {
      const { data } = await api.get("/livre/driver/fleet-tags");
      setFleetTags(Array.isArray(data) ? data : []);
    } catch (e) {
      console.debug("[DriverConsole] fleet-tags fetch failed:", e);
    }
  }

  useEffect(() => {
    loadSession();
    loadFleetTags();
    const t = setInterval(loadSession, 10000); // poll every 10s
    return () => clearInterval(t);
  }, []);

  async function testTag(t) {
    setTestingTagId(t.id);
    try {
      for (let i = 0; i < 3; i++) {
        await api.post("/livre/ble/detections", {
          identifier: t.identifier_raw || t.identifier,
          rssi: -55 - Math.floor(Math.random() * 10),
          platform: "pwa",
          battery: 78,
        });
      }
      toast.success(`Tag « ${t.identifier_raw || t.identifier} » envoyé`);
      await loadSession();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    } finally { setTestingTagId(null); }
  }

  async function stopDriving() {
    setSending(true);
    try {
      const { data } = await api.post("/livre/driver/stop");
      if (data.stopped) {
        toast.success(`Session terminée${data.vehicle_plate ? ` — ${data.vehicle_plate}` : ""}`);
        setSession(null);
      } else {
        toast.info(data.message || "Aucune session active");
      }
      await loadSession();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    } finally { setSending(false); }
  }

  async function setMode(mode) {
    setSending(true);
    try {
      const { data } = await api.post("/livre/driver/manual-mode", { mode });
      setSession({ ...session, mobile_override: mode, status: "manual" });
      toast.success(`Mode ${mode === "professional" ? "PROFESSIONNEL" : "PRIVÉ"} activé · ${data.trips_affected} trajet(s) impacté(s)`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    } finally { setSending(false); }
  }

  async function doLogout() {
    await logout();
    navigate("/login");
  }

  const isPro = session?.mobile_override === "professional";
  const isPerso = session?.mobile_override === "personal";

  return (
    <div data-testid="driver-console-page" className="min-h-screen bg-slate-900 text-white flex flex-col">
      {/* Top bar */}
      <header className="bg-slate-950/60 backdrop-blur px-4 py-3 flex items-center justify-between border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Smartphone className="w-5 h-5 text-[#2196F3]" />
          <div>
            <p className="text-xs uppercase tracking-wider text-slate-400 font-mono">LOGITRAK · Chauffeur</p>
            <p className="text-sm font-semibold">{user?.name || user?.email}</p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={doLogout} className="text-slate-300 hover:text-white hover:bg-slate-800"
          data-testid="driver-logout">
          <LogOut className="w-4 h-4" />
        </Button>
      </header>

      <main className="flex-1 px-4 py-5 max-w-md mx-auto w-full flex flex-col gap-4">
        {/* Vehicle card */}
        <Card className="bg-slate-800 border-slate-700 text-white p-5" data-testid="driver-vehicle-card">
          {loading ? (
            <div className="py-8 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
          ) : !session ? (
            <div className="text-center py-2">
              <Truck className="w-8 h-8 text-slate-500 mx-auto mb-2" />
              <p className="text-sm font-semibold">Aucun véhicule détecté</p>
              <p className="text-xs text-slate-400 mt-1">
                Approchez-vous d&apos;un véhicule équipé d&apos;un tag BLE LOGITRAK.
              </p>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <p className="text-[10px] uppercase tracking-wider text-slate-400">Véhicule détecté</p>
                <span className="flex items-center gap-1.5 text-[11px] text-emerald-300">
                  <Pulse active /> Connecté
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-lg bg-slate-700 flex items-center justify-center">
                  <Truck className="w-6 h-6 text-[#2196F3]" />
                </div>
                <div>
                  <p className="font-mono text-lg font-semibold tracking-tight" data-testid="driver-vehicle-plate">
                    {session.vehicle?.plate || "—"}
                  </p>
                  <p className="text-xs text-slate-400">{session.vehicle?.model}</p>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">Signal BLE</p>
                  <p className="font-mono mt-0.5">{session.last_rssi} dBm</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">Détections</p>
                  <p className="font-mono mt-0.5">{session.detection_count ?? 0}</p>
                </div>
              </div>
              <div className="mt-3">
                <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Score de confiance</p>
                <Confidence value={session.confidence} />
              </div>
            </>
          )}
        </Card>

        {/* Mode toggle */}
        <div className="grid grid-cols-2 gap-3">
          <button
            data-testid="driver-mode-pro"
            disabled={!session || sending}
            onClick={() => setMode("professional")}
            className={`relative rounded-2xl p-5 transition-all border-2 ${
              isPro
                ? "bg-[#2196F3] border-[#2196F3] shadow-lg shadow-blue-500/30 scale-[1.02]"
                : "bg-slate-800 border-slate-700 hover:border-slate-600 active:scale-[0.98]"
            } ${(!session || sending) ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            <Briefcase className={`w-8 h-8 mx-auto mb-2 ${isPro ? "text-white" : "text-[#2196F3]"}`} />
            <p className={`text-lg font-bold ${isPro ? "text-white" : "text-slate-100"}`}>PRO</p>
            <p className="text-[10px] uppercase tracking-wider text-slate-300 mt-1">Professionnel</p>
            {isPro && <span className="absolute top-2 right-2 text-[9px] bg-white text-blue-700 px-1.5 py-0.5 rounded font-bold">ACTIF</span>}
          </button>

          <button
            data-testid="driver-mode-perso"
            disabled={!session || sending}
            onClick={() => setMode("personal")}
            className={`relative rounded-2xl p-5 transition-all border-2 ${
              isPerso
                ? "bg-slate-200 border-slate-200 shadow-lg shadow-slate-500/30 scale-[1.02]"
                : "bg-slate-800 border-slate-700 hover:border-slate-600 active:scale-[0.98]"
            } ${(!session || sending) ? "opacity-40 cursor-not-allowed" : ""}`}
          >
            <UserIcon className={`w-8 h-8 mx-auto mb-2 ${isPerso ? "text-slate-700" : "text-slate-400"}`} />
            <p className={`text-lg font-bold ${isPerso ? "text-slate-900" : "text-slate-100"}`}>PRIVÉ</p>
            <p className={`text-[10px] uppercase tracking-wider mt-1 ${isPerso ? "text-slate-600" : "text-slate-300"}`}>Personnel</p>
            {isPerso && <span className="absolute top-2 right-2 text-[9px] bg-slate-900 text-white px-1.5 py-0.5 rounded font-bold">ACTIF</span>}
          </button>
        </div>

        {session && (
          <Button
            data-testid="driver-stop-btn"
            disabled={sending}
            onClick={stopDriving}
            className="w-full h-12 bg-rose-600 hover:bg-rose-500 text-white font-semibold rounded-2xl"
          >
            <Square className="w-4 h-4 mr-2" /> Je m&apos;arrête
          </Button>
        )}

        {session?.mobile_override && (
          <Card className="bg-amber-500/10 border-amber-500/30 text-amber-200 p-3 text-xs flex gap-2 items-start"
            data-testid="driver-override-banner">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <div>
              <p className="font-semibold">Mode {session.mobile_override === "professional" ? "PROFESSIONNEL" : "PRIVÉ"} forcé</p>
              <p className="text-[11px] mt-0.5 opacity-80">
                Tous les nouveaux trajets sur ce véhicule seront classés ainsi jusqu&apos;à votre prochain changement de véhicule.
              </p>
            </div>
          </Card>
        )}

        {/* BLE Scanner status */}
        <Card className="bg-slate-800 border-slate-700 text-slate-200 p-4" data-testid="driver-scanner-card">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <RadioTower className="w-3 h-3" /> Scanner Bluetooth
            </p>
            <span
              data-testid="driver-scanner-status"
              className={`flex items-center gap-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full border ${
                scanner.scanning
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
                  : scanner.support === "ok"
                    ? "bg-slate-700/60 text-slate-300 border-slate-600"
                    : "bg-rose-500/15 text-rose-300 border-rose-500/40"
              }`}
            >
              <Pulse active={scanner.scanning} />
              {scanner.scanning
                ? "Actif"
                : scanner.support === "ok"
                  ? "Inactif"
                  : "Indisponible"}
            </span>
          </div>
          {scanner.support !== "ok" && (
            <p className="text-[11px] text-amber-300/90 leading-relaxed mb-2"
               data-testid="driver-scanner-warning">
              {scanner.support === "no-bluetooth"
                ? "Web Bluetooth indisponible. Sur iPhone, l'app native Expo sera nécessaire (Phase B)."
                : "Le scan BLE nécessite Chrome Android. Ouvrez cette page depuis Chrome sur Android."}
            </p>
          )}
          {scanner.error && (
            <p className="text-[11px] text-rose-300 mb-2" data-testid="driver-scanner-error">
              {scanner.error}
            </p>
          )}
          {scanner.lastEvent && (
            <p className="text-[10px] text-slate-400 font-mono mb-2" data-testid="driver-scanner-last">
              dernier signal : {scanner.lastEvent.id} · {scanner.lastEvent.rssi} dBm
            </p>
          )}
          <div className="flex gap-2">
            {!scanner.scanning ? (
              <Button
                size="sm"
                onClick={scanner.start}
                disabled={scanner.support !== "ok"}
                data-testid="driver-scanner-start"
                className="bg-emerald-600 hover:bg-emerald-500 text-white flex-1 h-9 disabled:opacity-40"
              >
                <Play className="w-3.5 h-3.5 mr-1.5" /> Démarrer le scan
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={scanner.stop}
                data-testid="driver-scanner-stop"
                className="bg-rose-600 hover:bg-rose-500 text-white flex-1 h-9"
              >
                <Square className="w-3.5 h-3.5 mr-1.5" /> Arrêter
              </Button>
            )}
          </div>
        </Card>

        {/* Fleet tags */}
        <Card className="bg-slate-800/60 border-slate-700 text-slate-200 p-4" data-testid="driver-fleet-tags-card">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Tag className="w-3 h-3" /> Tags BLE de la flotte
            </p>
            <span className="text-[10px] text-slate-500 font-mono">{fleetTags.length}</span>
          </div>
          {fleetTags.length === 0 ? (
            <p className="text-[11px] text-slate-500 py-2">
              Aucun tag enregistré. Demandez à un administrateur d&apos;associer vos beacons aux véhicules.
            </p>
          ) : (
            <div className="max-h-[180px] overflow-y-auto -mx-1 px-1 space-y-1.5">
              {fleetTags.map((t) => (
                <div
                  key={t.id}
                  data-testid={`driver-fleet-tag-${t.id}`}
                  className="flex items-center justify-between gap-2 px-2.5 py-2 rounded-md bg-slate-900/60 border border-slate-700/60"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-mono text-[#9EE9FF] truncate">
                      {t.identifier_raw || t.identifier}
                    </p>
                    <p className="text-[10px] text-slate-400 truncate">
                      {t.vehicle_plate || "—"}{t.vehicle_model ? ` · ${t.vehicle_model}` : ""}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={testingTagId === t.id}
                    onClick={() => testTag(t)}
                    data-testid={`driver-fleet-tag-test-${t.id}`}
                    className="h-7 text-[10px] text-[#2196F3] hover:bg-blue-500/10 px-2"
                  >
                    {testingTagId === t.id
                      ? <Loader2 className="w-3 h-3 animate-spin" />
                      : <><Bluetooth className="w-3 h-3 mr-1" /> Tester</>}
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Simulator removed — fleet tags list above provides a "Tester" button per tag. */}

        <Button variant="ghost" size="sm" onClick={loadSession}
          className="text-slate-400 hover:text-white hover:bg-slate-800 mt-2"
          data-testid="driver-refresh">
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Rafraîchir
        </Button>
      </main>
    </div>
  );
}
