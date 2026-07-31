import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Save, RefreshCw, Landmark, AlertTriangle, Car } from "lucide-react";

function VehicleCapacitiesCard() {
  const [rows, setRows] = useState(null);
  const [savingId, setSavingId] = useState(null);

  useEffect(() => {
    api.get("/livre/fuel/vehicles-capacities").then(({ data }) => setRows(data)).catch(() => setRows([]));
  }, []);

  const setField = (id, field, value) =>
    setRows((r) => r.map((v) => (v.id === id ? { ...v, [field]: value } : v)));

  async function saveRow(v) {
    setSavingId(v.id);
    try {
      await api.patch(`/livre/fuel/vehicles/${v.id}/capacity`, {
        tank_capacity_l: v.tank_capacity_l === "" || v.tank_capacity_l == null ? null : Number(v.tank_capacity_l),
        battery_capacity_kwh: v.battery_capacity_kwh === "" || v.battery_capacity_kwh == null ? null : Number(v.battery_capacity_kwh),
      });
      toast.success(`Capacités de ${v.plate || "véhicule"} enregistrées`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSavingId(null); }
  }

  return (
    <div data-testid="fuel-vehicle-capacities-card" className="bg-white rounded-lg border border-slate-200 p-5 space-y-3">
      <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
        <Car className="w-3.5 h-3.5" /> Capacités des véhicules
      </p>
      <p className="text-[10px] text-slate-400">
        Nécessaire à l'alerte « volume supérieur au réservoir ». Sans capacité renseignée,
        aucune alerte de volume n'est émise pour le véhicule.
      </p>
      {!rows ? <p className="text-xs text-slate-400">Chargement…</p> : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase text-slate-400 border-b border-slate-200">
              <th className="py-1.5">Véhicule</th><th className="py-1.5">Réservoir (L)</th>
              <th className="py-1.5">Batterie (kWh)</th><th className="py-1.5"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => (
              <tr key={v.id} className="border-b border-slate-100">
                <td className="py-1.5 font-medium">{v.plate || v.label || v.id}</td>
                <td className="py-1.5 pr-2">
                  <Input data-testid={`fuel-capacity-tank-${v.id}`} type="number" className="h-7 w-24 text-xs"
                         value={v.tank_capacity_l ?? ""} placeholder="—"
                         onChange={(e) => setField(v.id, "tank_capacity_l", e.target.value)} />
                </td>
                <td className="py-1.5 pr-2">
                  <Input data-testid={`fuel-capacity-battery-${v.id}`} type="number" className="h-7 w-24 text-xs"
                         value={v.battery_capacity_kwh ?? ""} placeholder="—"
                         onChange={(e) => setField(v.id, "battery_capacity_kwh", e.target.value)} />
                </td>
                <td className="py-1.5 text-right">
                  <Button data-testid={`fuel-capacity-save-${v.id}`} variant="outline" size="sm"
                          className="h-7 text-xs" disabled={savingId === v.id}
                          onClick={() => saveRow(v)}>
                    {savingId === v.id ? "…" : "Enregistrer"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function FxCard() {
  const [st, setSt] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(() => {
    api.get("/livre/fuel/fx/status").then(({ data }) => setSt(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  async function syncNow() {
    setSyncing(true);
    try {
      const { data } = await api.post("/livre/fuel/fx/sync");
      toast.success(`Taux BCE à jour (dernier : ${data.latest_rate_date}) — ${data.converted} conversion(s) appliquée(s)`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSyncing(false); }
  }

  const chf = (st?.sample_rates || []).find((r) => r.currency === "CHF");
  const usd = (st?.sample_rates || []).find((r) => r.currency === "USD");

  return (
    <div data-testid="fuel-fx-card" className="bg-white rounded-lg border border-slate-200 p-5 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
          <Landmark className="w-3.5 h-3.5" /> Taux de change (BCE)
        </p>
        <Button data-testid="fuel-fx-sync-btn" variant="outline" size="sm" onClick={syncNow} disabled={syncing}>
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${syncing ? "animate-spin" : ""}`} />
          {syncing ? "Synchronisation…" : "Synchroniser maintenant"}
        </Button>
      </div>
      {!st ? <p className="text-xs text-slate-400">Chargement…</p> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div>
            <p className="text-slate-400">Dernier taux publié</p>
            <p data-testid="fuel-fx-latest-date" className="font-semibold text-slate-800">{st.latest_rate_date || "Aucun"}</p>
          </div>
          <div>
            <p className="text-slate-400">Dernière synchro</p>
            <p className="font-semibold text-slate-800">{st.last_success_at ? fmtDateTime(st.last_success_at) : "Jamais"}</p>
          </div>
          <div>
            <p className="text-slate-400">Taux du jour</p>
            <p className="font-semibold text-slate-800">
              {chf ? `1 EUR = ${chf.rate_per_eur} CHF` : "—"}
              {usd && <span className="block text-[10px] text-slate-400 font-normal">1 EUR = {usd.rate_per_eur} USD</span>}
            </p>
          </div>
          <div>
            <p className="text-slate-400">Conversions en attente</p>
            <p data-testid="fuel-fx-pending" className={`font-semibold ${st.pending_count ? "text-amber-600" : "text-slate-800"}`}>
              {st.pending_count}
            </p>
          </div>
        </div>
      )}
      {st?.last_error && (
        <p data-testid="fuel-fx-error" className="text-xs text-rose-600">
          Dernière erreur BCE : {st.last_error} — les taux existants restent utilisés.
        </p>
      )}
      <p className="text-[10px] text-slate-400">
        Taux de référence publiés par la Banque centrale européenne les jours ouvrés (~16h). Week-ends et jours
        fériés : dernier taux antérieur. Synchronisation automatique quotidienne à 16h20. Le montant et la devise
        d'origine sont toujours conservés ; les transactions clôturées ne sont jamais recalculées.
      </p>
    </div>
  );
}

export default function FuelSettingsPage() {
  const [s, setS] = useState(null);
  const [providersText, setProvidersText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/livre/fuel/settings").then(({ data }) => {
      setS(data);
      setProvidersText((data.providers || []).join(", "));
    }).catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, []);

  async function save() {
    setSaving(true);
    try {
      const { data } = await api.put("/livre/fuel/settings", {
        station_radius_m: Number(s.station_radius_m),
        score_auto: Number(s.score_auto),
        score_review: Number(s.score_review),
        time_window_min: Number(s.time_window_min),
        allocation_mode: s.allocation_mode,
        providers: providersText.split(",").map((p) => p.trim()).filter(Boolean),
        anomalies: {
          tank_enabled: !!s.anomalies?.tank_enabled,
          tank_tolerance_pct: Number(s.anomalies?.tank_tolerance_pct),
          card_enabled: !!s.anomalies?.card_enabled,
          double_enabled: !!s.anomalies?.double_enabled,
          double_window_min: Number(s.anomalies?.double_window_min),
          amount_enabled: !!s.anomalies?.amount_enabled,
          amount_multiplier: Number(s.anomalies?.amount_multiplier),
          amount_min_history: Number(s.anomalies?.amount_min_history),
        },
      });
      setS(data);
      toast.success("Paramètres enregistrés");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  if (!s) return <p className="text-sm text-slate-400">Chargement…</p>;

  return (
    <div data-testid="fuel-settings-page" className="space-y-4 max-w-2xl">
      <FxCard />
      <div className="bg-white rounded-lg border border-slate-200 p-5 space-y-4">
        <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Seuils de rapprochement</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Seuil « rapproché automatiquement » (score /100)</Label>
            <Input data-testid="fuel-settings-score-auto" type="number" min={1} max={100}
                   value={s.score_auto} onChange={(e) => setS({ ...s, score_auto: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Seuil « contrôle recommandé » (score /100)</Label>
            <Input data-testid="fuel-settings-score-review" type="number" min={1} max={100}
                   value={s.score_review} onChange={(e) => setS({ ...s, score_review: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Fenêtre temporelle trajets (minutes)</Label>
            <Input data-testid="fuel-settings-window" type="number" min={5} max={1440}
                   value={s.time_window_min} onChange={(e) => setS({ ...s, time_window_min: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Rayon autour de la station (mètres)</Label>
            <Input data-testid="fuel-settings-radius" type="number" min={50} max={5000}
                   value={s.station_radius_m} onChange={(e) => setS({ ...s, station_radius_m: e.target.value })} />
          </div>
        </div>
        <p className="text-xs text-slate-400">
          Sous le seuil de contrôle, la transaction reste « À vérifier ». Entre les deux seuils :
          « Contrôle recommandé ». Au-dessus du seuil automatique : rapprochée sans intervention.
        </p>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-5 space-y-4">
        <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Répartition & fournisseurs</p>
        <div className="space-y-1.5">
          <Label>Mode de répartition des coûts</Label>
          <Select value={s.allocation_mode} onValueChange={(v) => setS({ ...s, allocation_mode: v })}>
            <SelectTrigger data-testid="fuel-settings-allocation" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="A">Mode A — coût rattaché à l'événement (trajet / plein)</SelectItem>
              <SelectItem value="B">Mode B — répartition au prorata des km (Phase 2)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Fournisseurs de cartes (séparés par virgule)</Label>
          <Input data-testid="fuel-settings-providers" value={providersText}
                 onChange={(e) => setProvidersText(e.target.value)} />
          <p className="text-[10px] text-slate-400">
            Liste proposée à la création de carte et à l'import. Les connecteurs API fournisseurs arriveront en Phase 3.
          </p>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-5 space-y-4">
        <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5" /> Alertes anomalies
        </p>
        <div className="space-y-3" data-testid="fuel-anomaly-settings">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-800 font-medium">Volume supérieur au réservoir</p>
              <p className="text-[10px] text-slate-400">Muette si la capacité du véhicule est inconnue</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">Tolérance %</span>
              <Input data-testid="fuel-anomaly-tank-tolerance" type="number" className="h-8 w-20"
                     value={s.anomalies?.tank_tolerance_pct ?? ""}
                     onChange={(e) => setS({ ...s, anomalies: { ...s.anomalies, tank_tolerance_pct: e.target.value } })} />
              <Switch data-testid="fuel-anomaly-tank-enabled" checked={!!s.anomalies?.tank_enabled}
                      onCheckedChange={(v) => setS({ ...s, anomalies: { ...s.anomalies, tank_enabled: v } })} />
            </div>
          </div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-800 font-medium">Carte inactive, suspendue ou expirée</p>
              <p className="text-[10px] text-slate-400">Statut de la carte évalué au moment de la transaction</p>
            </div>
            <Switch data-testid="fuel-anomaly-card-enabled" checked={!!s.anomalies?.card_enabled}
                    onCheckedChange={(v) => setS({ ...s, anomalies: { ...s.anomalies, card_enabled: v } })} />
          </div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-800 font-medium">Deux pleins anormalement rapprochés</p>
              <p className="text-[10px] text-slate-400">Même carte ou même véhicule ; stations différentes signalées</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">Fenêtre (min)</span>
              <Input data-testid="fuel-anomaly-double-window" type="number" className="h-8 w-20"
                     value={s.anomalies?.double_window_min ?? ""}
                     onChange={(e) => setS({ ...s, anomalies: { ...s.anomalies, double_window_min: e.target.value } })} />
              <Switch data-testid="fuel-anomaly-double-enabled" checked={!!s.anomalies?.double_enabled}
                      onCheckedChange={(v) => setS({ ...s, anomalies: { ...s.anomalies, double_enabled: v } })} />
            </div>
          </div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-slate-800 font-medium">Montant inhabituel</p>
              <p className="text-[10px] text-slate-400">Comparé à la médiane historique du même véhicule — jamais de valeur fictive</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">× médiane</span>
              <Input data-testid="fuel-anomaly-amount-multiplier" type="number" step="0.1" className="h-8 w-20"
                     value={s.anomalies?.amount_multiplier ?? ""}
                     onChange={(e) => setS({ ...s, anomalies: { ...s.anomalies, amount_multiplier: e.target.value } })} />
              <span className="text-xs text-slate-500">min. hist.</span>
              <Input data-testid="fuel-anomaly-amount-minhistory" type="number" className="h-8 w-16"
                     value={s.anomalies?.amount_min_history ?? ""}
                     onChange={(e) => setS({ ...s, anomalies: { ...s.anomalies, amount_min_history: e.target.value } })} />
              <Switch data-testid="fuel-anomaly-amount-enabled" checked={!!s.anomalies?.amount_enabled}
                      onCheckedChange={(v) => setS({ ...s, anomalies: { ...s.anomalies, amount_enabled: v } })} />
            </div>
          </div>
        </div>
      </div>

      <VehicleCapacitiesCard />

      <Button data-testid="fuel-settings-save" onClick={save} disabled={saving}
              className="bg-[#2196F3] hover:bg-[#1976D2] text-white">
        <Save className="w-4 h-4 mr-1.5" /> {saving ? "Enregistrement…" : "Enregistrer"}
      </Button>
    </div>
  );
}
