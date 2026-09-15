import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Car, Loader2, Lock, AlertTriangle, RefreshCw, Play } from "lucide-react";
import { resolveVehicleSelection, storageKey } from "@/lib/driverVehicleSelection";

const MODE_LABEL = { ALL: "Tous les véhicules", SELECTED: "Accès restreint", SINGLE: "Véhicule attribué" };

export const DriverVehiclePicker = ({ userKey, refreshKey, onClaimed }) => {
  const [status, setStatus] = useState("loading");
  const [data, setData] = useState({ access_mode: null, default_vehicle_id: null, vehicles: [] });
  const [selectedId, setSelectedId] = useState(null);
  const [notice, setNotice] = useState(null);
  const [claiming, setClaiming] = useState(false);
  const selectedRef = useRef(null);
  selectedRef.current = selectedId;
  const key = storageKey(userKey);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const { data: d } = await api.get("/livre/driver/vehicles");
      const vehicles = Array.isArray(d?.vehicles) ? d.vehicles : [];
      let storedId = null;
      try { storedId = localStorage.getItem(key); } catch { /* storage indisponible */ }
      const res = resolveVehicleSelection({
        vehicles,
        defaultVehicleId: d?.default_vehicle_id,
        storedId,
        currentId: selectedRef.current,
      });
      if (res.purgeStored) { try { localStorage.removeItem(key); } catch { /* noop */ } }
      setNotice(res.revoked && vehicles.length > 0
        ? "Le véhicule précédemment sélectionné n'est plus autorisé pour votre compte. Il a été désélectionné."
        : null);
      setSelectedId(res.selectedId);
      if (res.selectedId) { try { localStorage.setItem(key, res.selectedId); } catch { /* noop */ } }
      setData({
        access_mode: d?.access_mode || null,
        default_vehicle_id: d?.default_vehicle_id || null,
        vehicles,
      });
      setStatus("ready");
    } catch {
      // Fail-closed : aucune liste, aucun fallback, aucune sélection.
      setData({ access_mode: null, default_vehicle_id: null, vehicles: [] });
      setSelectedId(null);
      setNotice(null);
      setStatus("error");
    }
  }, [key]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const locked = data.access_mode === "SINGLE";

  function selectVehicle(id) {
    if (locked || claiming) return;
    setSelectedId(id);
    setNotice(null);
    try { localStorage.setItem(key, id); } catch { /* noop */ }
  }

  async function claim() {
    if (!selectedId) return;
    setClaiming(true);
    try {
      const { data: r } = await api.post("/livre/driver/claim", {
        vehicle_id: selectedId,
        client_timestamp: new Date().toISOString(),
      });
      if (r?.status === "conflict") {
        toast.warning("Conflit : un autre chauffeur est actif sur ce véhicule. Résolution admin requise.");
      } else {
        toast.success("Session démarrée — vous conduisez ce véhicule");
      }
      onClaimed?.();
    } catch (e) {
      if (e?.response?.status === 403) {
        toast.error("Véhicule non autorisé pour votre compte");
        await load();
      } else {
        toast.error(e?.response?.data?.detail || "Échec de la confirmation");
      }
    } finally { setClaiming(false); }
  }

  return (
    <Card className="bg-slate-800 border-slate-700 text-slate-200 p-4" data-testid="driver-vehicles-card">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
          <Car className="w-3 h-3" /> Mes véhicules autorisés
        </p>
        {status === "ready" && data.access_mode && (
          <span
            data-testid="driver-vehicles-mode"
            className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
              locked
                ? "bg-amber-500/15 text-amber-300 border-amber-500/40"
                : "bg-slate-700/60 text-slate-300 border-slate-600"
            }`}
          >
            {locked && <Lock className="w-2.5 h-2.5" />}
            {MODE_LABEL[data.access_mode] || data.access_mode}
          </span>
        )}
      </div>

      {status === "loading" && (
        <div className="py-6 flex justify-center" data-testid="driver-vehicles-loading">
          <Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" />
        </div>
      )}

      {status === "error" && (
        <div className="py-3 text-center" data-testid="driver-vehicles-error">
          <AlertTriangle className="w-6 h-6 text-rose-400 mx-auto mb-2" />
          <p className="text-xs text-rose-300 font-semibold">Impossible de charger vos véhicules autorisés.</p>
          <p className="text-[11px] text-slate-400 mt-1">Par sécurité, aucun véhicule n&apos;est proposé.</p>
          <Button size="sm" variant="ghost" onClick={load} data-testid="driver-vehicles-retry"
            className="mt-2 h-8 text-[11px] text-[#2196F3] hover:bg-blue-500/10">
            <RefreshCw className="w-3 h-3 mr-1.5" /> Réessayer
          </Button>
        </div>
      )}

      {status === "ready" && data.vehicles.length === 0 && (
        <p className="text-[11px] text-slate-500 py-2" data-testid="driver-vehicles-empty">
          Aucun véhicule autorisé pour votre compte. Contactez un administrateur.
        </p>
      )}

      {status === "ready" && data.vehicles.length > 0 && (
        <>
          {notice && (
            <p className="text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-md px-2.5 py-2 mb-2 flex items-start gap-1.5"
              data-testid="driver-vehicles-notice">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {notice}
            </p>
          )}
          <div className="max-h-[200px] overflow-y-auto -mx-1 px-1 space-y-1.5">
            {data.vehicles.map((v) => {
              const active = v.id === selectedId;
              return (
                <button
                  key={v.id}
                  type="button"
                  data-testid={`driver-vehicle-option-${v.id}`}
                  onClick={() => selectVehicle(v.id)}
                  disabled={locked || claiming}
                  aria-pressed={active}
                  className={`w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-md border text-left transition-colors ${
                    active
                      ? "bg-blue-500/15 border-[#2196F3]/60"
                      : "bg-slate-900/60 border-slate-700/60 hover:border-slate-500"
                  } ${locked ? "cursor-default" : ""}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className={`text-xs font-mono truncate ${active ? "text-[#9EE9FF]" : "text-slate-200"}`}>
                      {v.plate || v.label || "—"}
                    </p>
                    <p className="text-[10px] text-slate-400 truncate">{v.model || v.label || ""}</p>
                  </div>
                  {active && (
                    <span className="text-[9px] bg-[#2196F3] text-white px-1.5 py-0.5 rounded font-bold shrink-0"
                      data-testid="driver-vehicle-selected-badge">
                      {locked ? "ATTRIBUÉ" : "SÉLECTIONNÉ"}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <Button
            data-testid="driver-claim-btn"
            disabled={!selectedId || claiming}
            onClick={claim}
            className="w-full h-10 mt-3 bg-[#2196F3] hover:bg-blue-500 text-white font-semibold rounded-xl disabled:opacity-40"
          >
            {claiming
              ? <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              : <Play className="w-4 h-4 mr-2" />}
            Je conduis ce véhicule
          </Button>
        </>
      )}
    </Card>
  );
};

export default DriverVehiclePicker;
