import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  Loader2, Briefcase, User as UserIcon, Smartphone, Truck, LogOut,
  RefreshCw, ChevronRight, ShieldAlert,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

/**
 * Console chauffeur — MODE MANUEL (sans Bluetooth).
 * Hiérarchie : Véhicule actuel -> Changer -> PRO/PRIVÉ -> Km Pro/Privé -> SOS.
 * Backend = seule source de vérité (session, PRO/PRIVÉ, km). Aucun calcul GPS local.
 * PRO/PRIVÉ appelle le VRAI Mode Privé (/driver/private-mode), pas la classification.
 */
export default function DriverConsolePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [vehicle, setVehicle] = useState(null);       // {id, plate, model}
  const [connected, setConnected] = useState(false);
  const [loadingVehicle, setLoadingVehicle] = useState(true);

  const [pm, setPm] = useState({ state: "UNKNOWN", allowed: false, reason: null, pending: false });
  const [pmBusy, setPmBusy] = useState(false);

  const [km, setKm] = useState({ pro: null, priv: null, label: "Mois en cours", available: false, loading: true });

  const [pickerOpen, setPickerOpen] = useState(false);
  const [myVehicles, setMyVehicles] = useState([]);
  const [switching, setSwitching] = useState(false);

  const [sosSending, setSosSending] = useState(false);
  const sosInFlight = useRef(false);
  const pmInFlight = useRef(false);
  const lastVehicleId = useRef(undefined);

  // --- Chargements ---
  const loadVehicle = useCallback(async () => {
    setLoadingVehicle(true);
    try {
      const { data } = await api.get("/livre/driver/my-vehicle");
      if (data?.vehicle?.id) { setVehicle(data.vehicle); setConnected(!!data.current); }
      else { setVehicle(null); setConnected(false); }
    } catch { setVehicle(null); setConnected(false); }
    finally { setLoadingVehicle(false); }
  }, []);

  const loadPrivateMode = useCallback(async () => {
    try {
      const { data } = await api.get("/livre/driver/private-mode");
      setPm(data);
    } catch {
      setPm((p) => ({ ...p, state: "UNKNOWN" }));
    }
  }, []);

  const loadKm = useCallback(async () => {
    setKm((k) => ({ ...k, loading: true }));
    try {
      const { data } = await api.get("/livre/driver/km-summary", { params: { period: "month" } });
      setKm({ pro: data.available ? data.pro_km : null, priv: data.available ? data.private_km : null,
              label: data.period_label || "Mois en cours",
              available: !!data.available, loading: false });
    } catch {
      setKm({ pro: null, priv: null, label: "Mois en cours", available: false, loading: false });
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadVehicle(), loadPrivateMode(), loadKm()]);
  }, [loadVehicle, loadPrivateMode, loadKm]);

  useEffect(() => {
    refreshAll();
    const t = setInterval(() => { loadPrivateMode(); }, 15000); // poll léger état
    return () => clearInterval(t);
  }, [refreshAll, loadPrivateMode]);

  // reset km quand le véhicule change (pas de contamination A -> B)
  useEffect(() => {
    const vid = vehicle?.id ?? null;
    if (lastVehicleId.current !== undefined && lastVehicleId.current !== vid) {
      setKm({ pro: null, priv: null, label: "Mois en cours", available: false, loading: true });
    }
    lastVehicleId.current = vid;
    if (vid) loadKm();
  }, [vehicle?.id, loadKm]);

  // --- Actions ---
  const openPicker = useCallback(async () => {
    setPickerOpen(true);
    try { const { data } = await api.get("/livre/driver/my-vehicles"); setMyVehicles(data?.vehicles || []); }
    catch { setMyVehicles([]); }
  }, []);

  const selectVehicle = useCallback(async (v) => {
    if (switching) return;
    setSwitching(true);
    try {
      await api.post("/livre/driver/claim", { vehicle_id: v.id });
      setPickerOpen(false);
      await refreshAll();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de sélectionner ce véhicule");
    } finally { setSwitching(false); }
  }, [switching, refreshAll]);

  const setMode = useCallback(async (mode) => {
    if (pmInFlight.current) return;   // anti double-clic
    pmInFlight.current = true;
    setPmBusy(true);
    try {
      const { data } = await api.post("/livre/driver/private-mode", { mode });
      if (data.ok === true && data.state === "PENDING_CONFIRMATION") {
        // commande envoyée, confirmation en cours -> JAMAIS "activé", pas d'état optimiste
        toast.info("Changement en cours de confirmation…");
      } else if (data.ok === true && (data.state === "PRIVATE" || data.state === "BUSINESS")) {
        toast.success(data.state === "PRIVATE" ? "Mode Privé activé." : "Mode Professionnel activé.");
      } else {
        // ok=false (ex. non confirmé, transition en cours) -> message honnête, aucun état optimiste
        toast.info(reasonMessage(data.reason, null));
      }
      // Dans TOUS les cas : on récupère l'état RÉEL du serveur (source de vérité).
      await loadPrivateMode();
    } catch (e) {
      const st = e?.response?.status;
      const detail = e?.response?.data?.detail;
      toast.error(reasonMessage(detail, st));
      await loadPrivateMode();
    } finally { setPmBusy(false); pmInFlight.current = false; }
  }, [loadPrivateMode]);

  const triggerSos = useCallback(async () => {
    if (sosInFlight.current) return;
    sosInFlight.current = true;
    setSosSending(true);
    try {
      const { data } = await api.post("/livre/driver/sos", { share_location: true });
      toast.success(data?.duplicate ? "Alerte déjà en cours." : "Alerte SOS envoyée. Les gestionnaires sont prévenus.");
    } catch {
      toast.error("Connexion indisponible. Alerte NON envoyée — réessayez.");
    } finally { setSosSending(false); sosInFlight.current = false; }
  }, []);

  const confirmSos = useCallback(() => {
    const extra = pm.state === "PRIVATE"
      ? " En cas d'urgence, votre position pourra être partagée pour permettre l'assistance."
      : "";
    if (window.confirm(`Déclencher une alerte SOS ?\n\nUne alerte va être envoyée aux gestionnaires.${extra}`)) {
      triggerSos();
    }
  }, [pm.state, triggerSos]);

  async function doLogout() { await logout(); navigate("/login"); }

  const st = pm.state;
  const isPrivate = st === "PRIVATE";
  const isBusiness = st === "BUSINESS";
  const isPending = st === "PENDING_CONFIRMATION" || st === "PRIVATE_REQUESTED" || st === "BUSINESS_REQUESTED";
  const hasVehicle = !!vehicle?.id;
  const canToggle = hasVehicle && pm.allowed && !pmBusy && !isPending;
  const fmtKm = (v) => (typeof v === "number" ? `${v.toFixed(1)} km` : "—");

  return (
    <div data-testid="driver-console-page" className="min-h-screen bg-slate-900 text-white flex flex-col">
      <header className="bg-slate-950/60 backdrop-blur px-4 py-3 flex items-center justify-between border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Smartphone className="w-5 h-5 text-[#2196F3]" />
          <div>
            <p className="text-xs uppercase tracking-wider text-slate-400 font-mono">LOGITRAK · Chauffeur</p>
            <p className="text-sm font-semibold">{user?.name || user?.email}</p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={doLogout} className="text-slate-300 hover:text-white hover:bg-slate-800" data-testid="driver-logout">
          <LogOut className="w-4 h-4" />
        </Button>
      </header>

      <main className="flex-1 px-4 py-5 max-w-md mx-auto w-full flex flex-col gap-4">
        {/* Véhicule actuel */}
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Véhicule actuel</p>
        <Card className="bg-slate-800 border-slate-700 text-white p-5" data-testid="driver-vehicle-card">
          {loadingVehicle ? (
            <div className="py-6 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
          ) : hasVehicle ? (
            <>
              <div className="flex items-center justify-between mb-3">
                <span className="flex items-center gap-2">
                  <span className="w-11 h-11 rounded-lg bg-slate-700 flex items-center justify-center"><Truck className="w-6 h-6 text-[#2196F3]" /></span>
                  <span>
                    <span className="block font-mono text-lg font-semibold" data-testid="driver-vehicle-plate">{vehicle.plate || "Véhicule"}</span>
                    {vehicle.model ? <span className="block text-xs text-slate-400">{vehicle.model}</span> : null}
                  </span>
                </span>
                <span className={`flex items-center gap-1.5 text-[11px] ${connected ? "text-emerald-300" : "text-slate-400"}`}>
                  <span className={`inline-block w-2 h-2 rounded-full ${connected ? "bg-emerald-500" : "bg-slate-500"}`} />
                  {connected ? "Connecté" : "Hors ligne"}
                </span>
              </div>
            </>
          ) : (
            <p className="text-sm text-slate-300 py-2" data-testid="driver-no-vehicle">Aucun véhicule sélectionné</p>
          )}
          <Button onClick={openPicker} data-testid="driver-change-vehicle"
            className="w-full mt-2 h-11 bg-[#2196F3] hover:bg-[#1E88E5] text-white font-semibold rounded-xl">
            Changer de véhicule <ChevronRight className="w-4 h-4 ml-1" />
          </Button>
        </Card>

        {/* PRO / PRIVÉ */}
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Mode</p>
        <div className="grid grid-cols-2 gap-3">
          <button
            data-testid="driver-mode-pro" disabled={!canToggle || isBusiness}
            onClick={() => setMode("BUSINESS")}
            className={`relative rounded-2xl p-5 border-2 transition-all ${isBusiness
              ? "bg-[#2196F3] border-[#2196F3] shadow-lg shadow-blue-500/30"
              : "bg-slate-800 border-slate-700 hover:border-slate-600"} ${(!canToggle || isBusiness) ? "opacity-50 cursor-not-allowed" : ""}`}
          >
            <Briefcase className={`w-8 h-8 mx-auto mb-2 ${isBusiness ? "text-white" : "text-[#2196F3]"}`} />
            <p className="text-lg font-bold">Professionnel</p>
            {isBusiness && <span className="absolute top-2 right-2 text-[9px] bg-white text-blue-700 px-1.5 py-0.5 rounded font-bold">ACTIF</span>}
          </button>
          <button
            data-testid="driver-mode-private" disabled={!canToggle || isPrivate}
            onClick={() => setMode("PRIVATE")}
            className={`relative rounded-2xl p-5 border-2 transition-all ${isPrivate
              ? "bg-slate-200 border-slate-200 shadow-lg"
              : "bg-slate-800 border-slate-700 hover:border-slate-600"} ${(!canToggle || isPrivate) ? "opacity-50 cursor-not-allowed" : ""}`}
          >
            <UserIcon className={`w-8 h-8 mx-auto mb-2 ${isPrivate ? "text-slate-700" : "text-slate-400"}`} />
            <p className={`text-lg font-bold ${isPrivate ? "text-slate-900" : "text-slate-100"}`}>Privé</p>
            {isPrivate && <span className="absolute top-2 right-2 text-[9px] bg-slate-900 text-white px-1.5 py-0.5 rounded font-bold">ACTIF</span>}
          </button>
        </div>

        {/* Aide contextuelle (sans jargon) */}
        {hasVehicle && pm.allowed ? (
          <p className="text-xs text-slate-400 leading-relaxed" data-testid="driver-mode-help">
            {isPrivate
              ? (pm.private_odometer_supported
                  ? "Mode Privé actif. Votre position est masquée. Vos kilomètres privés continuent d'être comptabilisés."
                  : "Mode Privé actif. Votre position est masquée.")
              : isBusiness
              ? "Mode Professionnel actif. Les nouveaux trajets seront enregistrés comme professionnels."
              : isPending
              ? "Changement en cours de confirmation…"
              : "Sélectionnez votre mode."}
          </p>
        ) : hasVehicle && !pm.allowed && pm.reason === "PRIVATE_MODE_NOT_SUPPORTED" ? (
          <p className="text-xs text-slate-400" data-testid="driver-mode-unavailable">Mode Privé indisponible pour ce véhicule.</p>
        ) : null}

        {/* Km Professionnels / Km Privés — mois en cours */}
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Kilomètres — {km.label}</p>
        <div className="grid grid-cols-2 gap-3">
          <Card className="bg-slate-800 border-slate-700 p-4" data-testid="driver-km-pro">
            <p className="text-xs font-semibold text-slate-100">Km Professionnels</p>
            <p className="text-[10px] text-slate-500 mb-1">{km.label}</p>
            <p className="text-2xl font-bold text-[#2196F3]">{km.loading ? "…" : fmtKm(km.pro)}</p>
          </Card>
          <Card className="bg-slate-800 border-slate-700 p-4" data-testid="driver-km-private">
            <p className="text-xs font-semibold text-slate-100">Km Privés</p>
            <p className="text-[10px] text-slate-500 mb-1">{km.label}</p>
            <p className="text-2xl font-bold text-slate-100">{km.loading ? "…" : fmtKm(km.priv)}</p>
          </Card>
        </div>

        {/* SOS Urgence */}
        <Button
          onClick={confirmSos} disabled={sosSending}
          data-testid="driver-sos-button"
          className="w-full h-14 mt-2 bg-rose-600 hover:bg-rose-500 text-white text-lg font-bold rounded-2xl tracking-wide"
        >
          {sosSending ? <Loader2 className="w-5 h-5 animate-spin" /> : (<><ShieldAlert className="w-5 h-5 mr-2" /> SOS Urgence</>)}
        </Button>

        <Button variant="ghost" size="sm" onClick={refreshAll}
          className="text-slate-400 hover:text-white hover:bg-slate-800 mt-1" data-testid="driver-refresh">
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Rafraîchir
        </Button>
      </main>

      {/* Modal : Choisir un véhicule (assignés) */}
      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="bg-slate-900 border-slate-700 text-white" data-testid="driver-vehicle-picker">
          <DialogHeader><DialogTitle>Choisir un véhicule</DialogTitle></DialogHeader>
          {myVehicles.length === 0 ? (
            <p className="text-sm text-slate-400 py-4" data-testid="driver-picker-empty">Aucun véhicule disponible</p>
          ) : (
            <div className="max-h-[60vh] overflow-y-auto space-y-2">
              {myVehicles.map((v) => {
                const selected = v.id === vehicle?.id;
                return (
                  <button key={v.id} disabled={switching}
                    onClick={() => selectVehicle(v)}
                    data-testid={`driver-picker-item-${v.id}`}
                    className={`w-full flex items-center justify-between p-3 rounded-lg border text-left ${selected ? "border-[#2196F3] bg-blue-500/10" : "border-slate-700 bg-slate-800 hover:border-slate-600"}`}
                  >
                    <span>
                      <span className="block font-mono font-semibold">{v.plate || "Véhicule"}</span>
                      {v.model ? <span className="block text-xs text-slate-400">{v.model}</span> : null}
                    </span>
                    {selected ? <span className="text-[10px] text-[#2196F3] font-bold">Actuel</span> : null}
                  </button>
                );
              })}
            </div>
          )}
          {switching ? <div className="flex justify-center pt-2"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div> : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// Messages simples (sans jargon) selon raison gate / code HTTP.
function reasonMessage(reason, httpStatus) {
  switch (reason) {
    case "PRIVATE_MODE_FEATURE_DISABLED":
    case "PRIVATE_MODE_TENANT_NOT_ALLOWED":
    case "PRIVATE_MODE_VEHICLE_NOT_PILOT":
      return "Le mode Privé n'est pas disponible pour le moment.";
    case "PRIVATE_MODE_KILL_SWITCH_ACTIVE":
    case "PRIVATE_MODE_INTEGRATION_UNAVAILABLE":
      return "Mode Privé temporairement indisponible. Réessayez plus tard.";
    case "PRIVATE_MODE_NOT_SUPPORTED":
      return "Le mode Privé n'est pas disponible pour ce véhicule.";
    case "PRIVATE_MODE_NO_TRACKER":
    case "PRIVATE_MODE_NO_VEHICLE":
      return "Aucun véhicule actif.";
    case "not_confirmed":
      return "Le changement n'a pas encore été confirmé. Réessayez dans un instant.";
    case "transition_in_progress":
      return "Un changement de mode est déjà en cours…";
  }
  if (httpStatus === 409) return "Le changement n'a pas pu être effectué car l'état du véhicule a changé.";
  if (httpStatus === 503) return "Mode Privé temporairement indisponible. Réessayez plus tard.";
  if (httpStatus === 401 || httpStatus === 403) return "Action non autorisée ou session expirée.";
  return "Action impossible pour le moment.";
}
