import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { TEST_IDS } from "@/constants/testIds";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { Shield, Eye, EyeOff, Briefcase, Loader2, Save, Truck, RefreshCw, Cloud, CloudOff, Clock, Power } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import AssignmentsDialog from "@/components/livre/AssignmentsDialog";

const MODE_OPTIONS = [
  { id: "A", testId: TEST_IDS.settings.modeA, icon: Eye, label: "Personnel visible",
    desc: "Le gestionnaire voit la carte, l'itinéraire, les adresses et l'historique complet.", color: "blue" },
  { id: "B", testId: TEST_IDS.settings.modeB, icon: EyeOff, label: "Personnel masqué",
    desc: "Seules les métriques (km, temps, carburant) sont visibles. Carte, adresses et GPS masqués.", color: "slate" },
  { id: "C", testId: TEST_IDS.settings.modeC, icon: Briefcase, label: "100 % professionnel",
    desc: "Tous les trajets sont considérés professionnels. Aucune classification personnelle.", color: "emerald" },
];

const WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

export default function SettingsPage() {
  const { user } = useAuth();
  const [settings, setSettings] = useState(null);
  const [vehicles, setVehicles] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [navixy, setNavixy] = useState({ configured: false });
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [syncDays, setSyncDays] = useState(30);
  const [sched, setSched] = useState(null);
  const [schedSaving, setSchedSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [s, v, n, dr, sc] = await Promise.all([
        api.get("/livre/settings").then(r => r.data),
        api.get("/livre/vehicles").then(r => r.data),
        api.get("/livre/navixy/status").then(r => r.data).catch(() => ({ configured: false })),
        api.get("/livre/drivers").then(r => r.data),
        api.get("/livre/navixy/scheduler").then(r => r.data).catch(() => null),
      ]);
      setSettings(s); setVehicles(v); setNavixy(n); setDrivers(dr); setSched(sc);
    } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function syncNavixy() {
    setSyncing(true);
    try {
      const { data } = await api.post(`/livre/navixy/sync?days=${syncDays}`);
      setLastSync(data);
      toast.success(
        `Navixy : ${data.trips_new} nouveaux trajets, ${data.trips_updated} mis à jour · ${data.trackers_with_data}/${data.trackers} véhicules actifs`
      );
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Synchronisation impossible");
    } finally { setSyncing(false); }
  }

  async function saveScheduler() {
    if (!sched) return;
    setSchedSaving(true);
    try {
      const { data } = await api.put(`/livre/navixy/scheduler`, {
        enabled: sched.enabled, interval_min: sched.interval_min, days: sched.days,
      });
      setSched(data);
      toast.success(sched.enabled
        ? `Sync auto activée — toutes les ${data.interval_min} min`
        : "Sync auto désactivée");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Refusé");
    } finally { setSchedSaving(false); }
  }

  async function runNow() {
    setSchedSaving(true);
    try {
      const { data } = await api.post(`/livre/navixy/scheduler/run-now`);
      toast.success(`Sync exécutée · ${data.trips_new} nouveaux trajets`);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Refusé"); }
    finally { setSchedSaving(false); }
  }

  async function save() {
    setSaving(true);
    try {
      await api.put("/livre/settings", { mode: settings.mode, rules: settings.rules });
      toast.success("Paramètres enregistrés — règles réappliquées");
      load();
    } catch (e) {
      toast.error("Enregistrement refusé");
    } finally { setSaving(false); }
  }

  async function changeVehicleMode(vehicleId, mode) {
    try {
      await api.put(`/livre/vehicles/${vehicleId}/mode`, { mode });
      toast.success("Mode véhicule mis à jour");
      load();
    } catch { toast.error("Refusé"); }
  }

  if (loading || !settings) {
    return <div className="py-24 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>;
  }

  const canEdit = user?.role === "admin" || user?.role === "manager";
  const toggleWeekend = (dayIdx) => {
    const arr = settings.rules.weekend_days || [];
    const next = arr.includes(dayIdx) ? arr.filter(d => d !== dayIdx) : [...arr, dayIdx];
    setSettings({ ...settings, rules: { ...settings.rules, weekend_days: next.sort() } });
  };

  return (
    <div data-testid={TEST_IDS.settings.page} className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300 max-w-5xl">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Configuration</p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 mt-1 flex items-center gap-3">
          <Shield className="w-6 h-6 text-[#2196F3]" /> Paramètres du livre de bord
        </h1>
        <p className="text-sm text-slate-500 mt-1.5">
          Politique de confidentialité, moteur de règles automatiques et modes véhicules.
        </p>
      </div>

      {/* Navixy live sync */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex-1 min-w-[280px]">
            <h3 className="text-sm font-semibold text-slate-800 mb-1 flex items-center gap-2">
              {navixy.configured ? <Cloud className="w-4 h-4 text-[#2196F3]" /> : <CloudOff className="w-4 h-4 text-slate-400" />}
              Synchronisation Navixy
            </h3>
            <p className="text-xs text-slate-500 max-w-xl leading-relaxed">
              {navixy.configured
                ? "Connecté à l'API Navixy. La synchronisation importe les véhicules (tracker/list), les chauffeurs (employee/list), les zones (zone/list) et les trajets (track/list) sur la période sélectionnée."
                : "NAVIXY_HASH non configuré. Renseignez la clé API dans /app/backend/.env pour activer la synchronisation en temps réel."}
            </p>
            {lastSync && (
              <div className="mt-3 text-xs bg-blue-50 border border-blue-200 rounded-md px-3 py-2 text-slate-700 font-mono inline-flex gap-4 flex-wrap">
                <span>✓ {lastSync.trackers} véhicules</span>
                <span>· {lastSync.drivers} chauffeurs</span>
                <span>· {lastSync.zones} zones</span>
                <span>· {lastSync.trips_new} nouveaux</span>
                <span>· {lastSync.trips_updated} màj</span>
                {lastSync.reclassified !== undefined && <span>· {lastSync.reclassified} reclassifiés</span>}
              </div>
            )}
          </div>
          <div className="flex items-end gap-2">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Période (jours)</p>
              <Input
                type="number" min="1" max="365"
                data-testid="settings-navixy-days"
                disabled={!navixy.configured || syncing || user?.role !== "admin"}
                value={syncDays}
                onChange={(e) => setSyncDays(parseInt(e.target.value, 10) || 30)}
                className="w-24"
              />
            </div>
            <Button
              disabled={!navixy.configured || syncing || user?.role !== "admin"}
              onClick={syncNavixy}
              data-testid="settings-navixy-sync"
              className="bg-[#2196F3] hover:bg-[#1E88E5] text-white"
            >
              {syncing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <RefreshCw className="w-4 h-4 mr-2" />}
              Synchroniser
            </Button>
          </div>
        </div>

        {sched && (
          <div className="mt-5 pt-5 border-t border-slate-100">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex-1 min-w-[280px]">
                <p className="text-sm font-medium text-slate-800 flex items-center gap-2">
                  <Clock className="w-4 h-4 text-slate-500" /> Synchronisation automatique
                </p>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                  Lance une sync Navixy en arrière-plan à intervalle régulier. Idempotent : ne crée pas de doublons.
                </p>
                {sched.last_run && (
                  <p className="text-[11px] text-slate-500 mt-2 font-mono">
                    Dernière exécution : {new Date(sched.last_run).toLocaleString("fr-CH")}
                    {sched.last_result?.trips_new !== undefined && (
                      <span className="ml-2 text-emerald-600">+{sched.last_result.trips_new} trajets</span>
                    )}
                  </p>
                )}
                {sched.next_run && sched.enabled && (
                  <p className="text-[11px] text-slate-500 mt-1 font-mono">
                    Prochaine : {new Date(sched.next_run).toLocaleString("fr-CH")}
                  </p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2 items-end">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Intervalle (min)</p>
                  <Input type="number" min="1" max="1440"
                    data-testid="settings-sched-interval"
                    disabled={user?.role !== "admin"}
                    value={sched.interval_min}
                    onChange={(e) => setSched({ ...sched, interval_min: parseInt(e.target.value, 10) || 15 })}
                    className="w-28" />
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Période (jours)</p>
                  <Input type="number" min="1" max="365"
                    data-testid="settings-sched-days"
                    disabled={user?.role !== "admin"}
                    value={sched.days}
                    onChange={(e) => setSched({ ...sched, days: parseInt(e.target.value, 10) || 7 })}
                    className="w-24" />
                </div>
                <div className="col-span-2 flex items-center justify-between gap-3 pt-1">
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={!!sched.enabled}
                      disabled={user?.role !== "admin" || !navixy.configured}
                      data-testid="settings-sched-toggle"
                      onCheckedChange={(v) => setSched({ ...sched, enabled: v })}
                    />
                    <Label className="text-sm text-slate-700 flex items-center gap-1.5">
                      <Power className="w-3.5 h-3.5" /> {sched.enabled ? "Activée" : "Désactivée"}
                    </Label>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm" variant="outline"
                      disabled={user?.role !== "admin" || !navixy.configured || schedSaving}
                      data-testid="settings-sched-run-now"
                      onClick={runNow}
                    >
                      <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Lancer maintenant
                    </Button>
                    <Button
                      size="sm"
                      disabled={user?.role !== "admin" || schedSaving}
                      data-testid="settings-sched-save"
                      onClick={saveScheduler}
                      className="bg-slate-900 hover:bg-slate-800 text-white"
                    >
                      {schedSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <Save className="w-3.5 h-3.5 mr-1.5" />}
                      Appliquer
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </Card>

      {/* Privacy modes */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-6">
        <h3 className="text-sm font-semibold text-slate-800 mb-1">Politique de confidentialité</h3>
        <p className="text-xs text-slate-500 mb-5">Détermine ce que voient les gestionnaires des trajets personnels.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {MODE_OPTIONS.map(opt => {
            const active = settings.mode === opt.id;
            return (
              <button
                key={opt.id} type="button"
                data-testid={opt.testId}
                disabled={!canEdit}
                onClick={() => setSettings({ ...settings, mode: opt.id })}
                className={`text-left rounded-md border p-4 transition-all ${
                  active
                    ? "border-[#2196F3] bg-blue-50 ring-2 ring-[#2196F3]/20"
                    : "border-slate-200 hover:border-slate-300 bg-white"
                } ${!canEdit ? "opacity-60 cursor-not-allowed" : ""}`}
              >
                <div className="flex items-center justify-between">
                  <opt.icon className={`w-5 h-5 ${active ? "text-[#2196F3]" : "text-slate-400"}`} />
                  <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${active ? "bg-[#2196F3] text-white" : "bg-slate-100 text-slate-500"}`}>
                    Mode {opt.id}
                  </span>
                </div>
                <p className={`mt-3 text-sm font-semibold ${active ? "text-[#1976D2]" : "text-slate-800"}`}>{opt.label}</p>
                <p className="mt-1 text-xs text-slate-500 leading-relaxed">{opt.desc}</p>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Time rules */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-6">
        <h3 className="text-sm font-semibold text-slate-800 mb-1">Règles automatiques</h3>
        <p className="text-xs text-slate-500 mb-5">Classification automatique des trajets non modifiés manuellement.</p>

        <div className="space-y-5">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4">
            <div>
              <p className="text-sm font-medium text-slate-800">Règle horaire</p>
              <p className="text-xs text-slate-500">Pendant les heures de travail = professionnel, hors heures = personnel.</p>
            </div>
            <Switch
              checked={!!settings.rules.time_enabled}
              disabled={!canEdit}
              onCheckedChange={(v) => setSettings({ ...settings, rules: { ...settings.rules, time_enabled: v } })}
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <Label htmlFor="ws" className="text-[10px] uppercase tracking-wider text-slate-400">Début journée</Label>
              <Input id="ws" type="number" min="0" max="23"
                data-testid={TEST_IDS.settings.timeStart}
                disabled={!canEdit || !settings.rules.time_enabled}
                value={settings.rules.work_start_hour}
                onChange={(e) => setSettings({ ...settings, rules: { ...settings.rules, work_start_hour: parseInt(e.target.value, 10) || 0 } })}
                className="mt-1.5" />
            </div>
            <div>
              <Label htmlFor="we" className="text-[10px] uppercase tracking-wider text-slate-400">Fin journée</Label>
              <Input id="we" type="number" min="0" max="23"
                data-testid={TEST_IDS.settings.timeEnd}
                disabled={!canEdit || !settings.rules.time_enabled}
                value={settings.rules.work_end_hour}
                onChange={(e) => setSettings({ ...settings, rules: { ...settings.rules, work_end_hour: parseInt(e.target.value, 10) || 0 } })}
                className="mt-1.5" />
            </div>
          </div>

          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">Jours considérés comme week-end</p>
            <div className="flex flex-wrap gap-2">
              {WEEKDAYS.map((d, i) => {
                const active = (settings.rules.weekend_days || []).includes(i);
                return (
                  <button
                    key={d} type="button"
                    disabled={!canEdit}
                    onClick={() => toggleWeekend(i)}
                    className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors ${
                      active
                        ? "bg-slate-800 text-white border-slate-800"
                        : "bg-white text-slate-600 border-slate-200 hover:border-slate-300"
                    }`}
                  >{d}</button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 pt-4">
            <div>
              <p className="text-sm font-medium text-slate-800">Règle géofences</p>
              <p className="text-xs text-slate-500">Départ/arrivée dans dépôt/client/chantier = pro, domicile = perso.</p>
            </div>
            <Switch
              checked={!!settings.rules.geofence_enabled}
              disabled={!canEdit}
              onCheckedChange={(v) => setSettings({ ...settings, rules: { ...settings.rules, geofence_enabled: v } })}
            />
          </div>
        </div>

        <div className="mt-6 pt-6 border-t border-slate-100 flex justify-end gap-2">
          <Button
            disabled={!canEdit || saving}
            data-testid={TEST_IDS.settings.save}
            onClick={save}
            className="bg-[#2196F3] hover:bg-[#1E88E5] text-white"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Save className="w-4 h-4 mr-2" />}
            Enregistrer les paramètres
          </Button>
        </div>
      </Card>

      {/* Vehicles */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-6">
        <h3 className="text-sm font-semibold text-slate-800 mb-1 flex items-center gap-2">
          <Truck className="w-4 h-4 text-slate-500" /> Modes véhicules & affectations
        </h3>
        <p className="text-xs text-slate-500 mb-5">Forçage de classification par véhicule + affectations chauffeurs (multi-véhicules, plages de dates).</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs font-medium uppercase tracking-wider">
                <th className="text-left py-3 px-4">Plaque</th>
                <th className="text-left py-3 px-4">Modèle</th>
                <th className="text-right py-3 px-4">Mode</th>
                <th className="text-right py-3 px-4">Affectations</th>
              </tr>
            </thead>
            <tbody>
              {vehicles.map(v => (
                <tr key={v.id} className="border-t border-slate-100">
                  <td className="py-3 px-4 font-mono text-xs">{v.plate}</td>
                  <td className="py-3 px-4 text-slate-700">{v.model}</td>
                  <td className="py-3 px-4 text-right">
                    <Select value={v.mode}
                      onValueChange={(val) => changeVehicleMode(v.id, val)}
                      disabled={!canEdit}>
                      <SelectTrigger
                        className="w-44 ml-auto"
                        data-testid={`${TEST_IDS.settings.vehicleModeSelect}-${v.plate.replace(/\s+/g, "-")}`}
                      ><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="mixte">Mixte</SelectItem>
                        <SelectItem value="always_pro">Toujours professionnel</SelectItem>
                        <SelectItem value="always_perso">Toujours personnel</SelectItem>
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <AssignmentsDialog
                      vehicle={v} drivers={drivers}
                      canEdit={canEdit}
                      onChanged={load}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
