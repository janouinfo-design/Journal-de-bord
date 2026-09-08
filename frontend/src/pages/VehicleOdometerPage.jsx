import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Loader2, Gauge, Truck, History, AlertTriangle } from "lucide-react";
import { canCalibrate as canCalibrateFn, syncDisabled, canAttemptCalibration } from "./vehicleOdometerLogic";

/**
 * Fiche véhicule — Kilométrage compteur (calibration baseline AVL16).
 * ADMIN / SUPERADMIN uniquement (le routing applique déjà le RBAC ; le backend reste autoritaire).
 * L'admin relève le kilométrage RÉEL du tableau de bord -> devient la baseline du Total Odometer.
 * Aucun jargon technique inutile. La saisie exige un ENTIER (11807 = km entier).
 */
export default function VehicleOdometerPage() {
  const [vehicles, setVehicles] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selected, setSelected] = useState(null);     // vehicle id
  const [state, setState] = useState(null);           // odometer state payload
  const [loadingState, setLoadingState] = useState(false);

  const [dashKm, setDashKm] = useState("");
  const [inputError, setInputError] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadVehicles = useCallback(async () => {
    setLoadingList(true);
    try {
      const { data } = await api.get("/livre/vehicles");
      setVehicles(Array.isArray(data) ? data : []);
    } catch {
      setVehicles([]);
    } finally {
      setLoadingList(false);
    }
  }, []);

  const loadState = useCallback(async (vid) => {
    if (!vid) return;
    setLoadingState(true);
    try {
      const { data } = await api.get(`/livre/vehicles/${vid}/odometer`);
      setState(data);
    } catch (e) {
      setState(null);
      toast.error(e?.response?.status === 403
        ? "Accès réservé aux administrateurs."
        : "Impossible de charger l'état du kilométrage.");
    } finally {
      setLoadingState(false);
    }
  }, []);

  useEffect(() => { loadVehicles(); }, [loadVehicles]);
  useEffect(() => { if (selected) { setDashKm(""); setInputError(null); loadState(selected); } }, [selected, loadState]);

  const telematicsKm = state?.telematics_km;
  const supported = !!state?.supported;
  // UI FAIL-CLOSED : le bouton n'est actif QUE si can_calibrate === true (booléen strict).
  // Jamais de fallback sur device_write_enabled : null/undefined/absent/erreur => désactivé.
  const canCalibrate = canCalibrateFn(state);

  // Validation stricte : entier uniquement (jamais tronqué silencieusement)
  const validate = (raw) => {
    const s = String(raw).trim().replace(/\s|'/g, "");
    if (s === "") return { error: "Saisir un kilométrage." };
    if (!/^\d+$/.test(s)) return { error: "Saisir un kilométrage ENTIER (sans décimale)." };
    const n = Number(s);
    const max = state?.param_max_km ?? 4294967;
    if (n < 0 || n > max) return { error: `Kilométrage hors plage (0 .. ${max} km).` };
    return { value: n };
  };

  const delta = useMemo(() => {
    const v = validate(dashKm).value;
    if (v === undefined || typeof telematicsKm !== "number") return null;
    return v - telematicsKm;
  }, [dashKm, telematicsKm]);

  const openConfirm = () => {
    // Garde fail-closed : jamais de confirmation/POST si la gate backend n'autorise pas.
    if (!canAttemptCalibration(state)) return;
    const { value, error } = validate(dashKm);
    if (error) { setInputError(error); return; }
    setInputError(null);
    setConfirmOpen(true);
  };

  const submit = async () => {
    const { value, error } = validate(dashKm);
    if (error) { setInputError(error); setConfirmOpen(false); return; }
    setSubmitting(true);
    try {
      const { data } = await api.post(`/livre/vehicles/${selected}/odometer/calibrate`,
        { dashboard_km: value, command_style: "setparam" });
      if (data.odometer_calibrated) {
        toast.success("Compteur synchronisé et confirmé.");
      } else {
        toast.info("Demande enregistrée, en attente de confirmation du véhicule.");
      }
      setConfirmOpen(false);
      await loadState(selected);
    } catch (e) {
      const st = e?.response?.status;
      const reason = e?.response?.data?.detail;
      if (reason === "ODOMETER_CALIBRATION_DEVICE_WRITE_DISABLED" || st === 503) {
        toast.info("La synchronisation du compteur est temporairement indisponible.");
      } else if (st === 403) {
        toast.error("Action réservée aux administrateurs.");
      } else if (reason === "ODOMETER_CALIBRATION_NOT_SUPPORTED") {
        toast.error("Ce véhicule ne supporte pas la synchronisation du compteur.");
      } else if (reason === "ODOMETER_CALIBRATION_DEVICE_OFFLINE") {
        toast.error("Véhicule hors ligne — synchronisation impossible pour le moment.");
      } else {
        toast.error("Synchronisation impossible pour le moment.");
      }
      setConfirmOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  const fmtKm = (v) => (typeof v === "number" ? `${v.toLocaleString("fr-CH", { maximumFractionDigits: 3 })} km` : "N/A");
  const fmtDate = (iso) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("fr-CH"); } catch { return String(iso); }
  };

  return (
    <div data-testid="vehicle-odometer-page" className="max-w-5xl mx-auto p-4 space-y-5">
      <div className="flex items-center gap-2">
        <Gauge className="w-6 h-6 text-[#2196F3]" />
        <div>
          <h1 className="text-xl font-semibold">Kilométrage compteur</h1>
          <p className="text-sm text-slate-500">Calibrer le compteur télématique à partir du tableau de bord du véhicule.</p>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        {/* Liste véhicules */}
        <Card className="p-3 md:col-span-1" data-testid="odo-vehicle-list">
          <p className="text-xs uppercase tracking-wide text-slate-400 mb-2">Véhicules</p>
          {loadingList ? (
            <div className="py-6 flex justify-center"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : vehicles.length === 0 ? (
            <p className="text-sm text-slate-500 py-3">Aucun véhicule.</p>
          ) : (
            <div className="max-h-[60vh] overflow-y-auto space-y-1">
              {vehicles.map((v) => (
                <button key={v.id} onClick={() => setSelected(v.id)}
                  data-testid={`odo-vehicle-${v.id}`}
                  className={`w-full text-left p-2 rounded-lg border flex items-center gap-2 ${selected === v.id ? "border-[#2196F3] bg-blue-50" : "border-slate-200 hover:border-slate-300"}`}>
                  <Truck className="w-4 h-4 text-slate-400" />
                  <span>
                    <span className="block font-mono text-sm font-semibold">{v.plate || "Véhicule"}</span>
                    {v.model ? <span className="block text-[11px] text-slate-400">{v.model}</span> : null}
                  </span>
                </button>
              ))}
            </div>
          )}
        </Card>

        {/* Détail / calibration */}
        <Card className="p-4 md:col-span-2" data-testid="odo-detail">
          {!selected ? (
            <p className="text-sm text-slate-500 py-8 text-center">Sélectionnez un véhicule.</p>
          ) : loadingState ? (
            <div className="py-10 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
          ) : !state ? (
            <p className="text-sm text-slate-500 py-8 text-center">État indisponible.</p>
          ) : !supported ? (
            <div className="py-6 text-center" data-testid="odo-unsupported">
              <p className="font-medium">{state.vehicle?.plate}</p>
              <p className="text-sm text-slate-500 mt-2">La synchronisation du compteur n&apos;est pas disponible pour ce véhicule.</p>
            </div>
          ) : (
            <div className="space-y-5">
              <div>
                <p className="font-mono text-lg font-semibold">{state.vehicle?.plate}</p>
                <p className="text-xs text-slate-400">{state.vehicle?.model}</p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 rounded-lg bg-slate-50 border border-slate-200">
                  <p className="text-xs text-slate-500">Kilométrage télématique</p>
                  <p className="text-2xl font-bold text-[#2196F3]" data-testid="odo-telematics-km">{fmtKm(telematicsKm)}</p>
                </div>
                <div className="p-3 rounded-lg bg-slate-50 border border-slate-200">
                  <p className="text-xs text-slate-500">Source</p>
                  <p className="text-sm font-medium mt-1">Teltonika AVL16</p>
                  <p className="text-[11px] text-slate-400 mt-1">Dernière mise à jour : {fmtDate(state.last_update)}</p>
                </div>
              </div>

              {!canCalibrate ? (
                <p className="text-xs text-amber-600 flex items-center gap-1" data-testid="odo-write-disabled">
                  <AlertTriangle className="w-3.5 h-3.5" /> La synchronisation du compteur est actuellement indisponible.
                </p>
              ) : null}

              {/* Saisie km tableau de bord */}
              <div>
                <label className="block text-sm font-medium mb-1">Kilométrage actuel du tableau de bord</label>
                <div className="flex items-center gap-2">
                  <Input
                    data-testid="odo-dashboard-input"
                    inputMode="numeric"
                    placeholder="ex. 139620"
                    value={dashKm}
                    onChange={(e) => { setDashKm(e.target.value); setInputError(null); }}
                    className="max-w-[200px]"
                  />
                  <span className="text-sm text-slate-500">km</span>
                  <Button onClick={openConfirm} disabled={syncDisabled({ state, submitting, dashKm })}
                    data-testid="odo-sync-button" className="bg-[#2196F3] hover:bg-[#1E88E5]">
                    Synchroniser avec le compteur
                  </Button>
                </div>
                {inputError ? <p className="text-xs text-red-600 mt-1" data-testid="odo-input-error">{inputError}</p> : null}
                {typeof delta === "number" && Math.abs(delta) >= (state.large_delta_warn_km ?? 1000) ? (
                  <p className="text-xs text-amber-600 mt-2" data-testid="odo-delta-warning">
                    Écart détecté : {delta > 0 ? "+" : ""}{delta.toLocaleString("fr-CH", { maximumFractionDigits: 0 })} km.
                    Confirmez que la valeur a été relevée directement sur le tableau de bord.
                  </p>
                ) : null}
              </div>

              {/* Historique */}
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-400 mb-2 flex items-center gap-1">
                  <History className="w-3.5 h-3.5" /> Historique des calibrations
                </p>
                {(state.calibrations || []).length === 0 ? (
                  <p className="text-sm text-slate-400" data-testid="odo-history-empty">Aucune calibration enregistrée.</p>
                ) : (
                  <div className="space-y-2 max-h-[30vh] overflow-y-auto" data-testid="odo-history">
                    {state.calibrations.map((c) => (
                      <div key={c.id} className="text-xs p-2 rounded border border-slate-200 bg-white">
                        <div className="flex justify-between">
                          <span>{fmtDate(c.calibrated_at)}</span>
                          <span className={c.odometer_calibrated ? "text-emerald-600 font-medium" : "text-amber-600 font-medium"}>
                            {c.result}
                          </span>
                        </div>
                        <div className="text-slate-500 mt-1">
                          Ancien AVL16 : {fmtKm(c.avl16_before_km)} · Tableau de bord : {fmtKm(c.requested_dashboard_km)} · Nouvel AVL16 : {fmtKm(c.avl16_after_km)}
                        </div>
                        <div className="text-slate-400">Par : {c.calibrated_by}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Confirmation avant écriture */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent data-testid="odo-confirm-dialog">
          <DialogHeader><DialogTitle>Confirmer la synchronisation</DialogTitle></DialogHeader>
          <div className="space-y-2 text-sm">
            <p>Kilométrage actuel (télématique) : <b>{fmtKm(telematicsKm)}</b></p>
            <p>Nouvelle valeur saisie : <b>{validate(dashKm).value?.toLocaleString("fr-CH")} km</b></p>
            {typeof delta === "number" ? (
              <p className="text-slate-500">Écart : {delta > 0 ? "+" : ""}{delta.toLocaleString("fr-CH", { maximumFractionDigits: 0 })} km</p>
            ) : null}
            <p className="text-slate-500 pt-1">Cette opération recalibrera le compteur télématique du véhicule.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={submitting}>Annuler</Button>
            <Button onClick={submit} disabled={submitting} data-testid="odo-confirm-submit"
              className="bg-[#2196F3] hover:bg-[#1E88E5]">
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : "Confirmer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
