import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { TEST_IDS } from "@/constants/testIds";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger,
} from "@/components/ui/sheet";
import { toast } from "sonner";
import {
  Shield, Eye, EyeOff, Loader2, Save, RefreshCw, Cloud, CloudOff, Truck,
  Power, Calendar, ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import AssignmentsDialog from "@/components/livre/AssignmentsDialog";
import ScheduleEditor from "@/components/livre/ScheduleEditor";
import PrivacyCompatCard from "@/components/livre/PrivacyCompatCard";
import PrivacyEnforcementCard from "@/components/livre/PrivacyEnforcementCard";

const MODE_OPTIONS = [
  {
    id: "mixte", testId: TEST_IDS.settings.modeA, icon: Eye, label: "Mode mixte", badge: "Mixte",
    desc: "Le gestionnaire consulte les trajets professionnels et personnels (carte, adresses, horaires, vitesses, carburant). Les rapports pro et perso restent séparés.",
  },
  {
    id: "masked", testId: TEST_IDS.settings.modeB, icon: EyeOff, label: "Personnel masqué", badge: "Masqué",
    desc: "Les trajets privés sont totalement anonymisés. Le gestionnaire voit uniquement les km personnels, le pourcentage et le carburant personnel (si activé). Aucune carte, date, durée, adresse ou vitesse n'est exposée.",
  },
];

function SectionHeader({ n, title, subtitle, icon: Icon, accent = "text-[#2196F3]" }) {
  return (
    <div className="flex items-start gap-3 mb-4">
      <span className={`shrink-0 w-7 h-7 rounded-full bg-[#2196F3] text-white text-xs font-semibold flex items-center justify-center mt-0.5`}>
        {n}
      </span>
      <div className="flex-1">
        <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
          {Icon && <Icon className={`w-4 h-4 ${accent}`} />} {title}
        </h2>
        {subtitle && <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{subtitle}</p>}
      </div>
    </div>
  );
}

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
  const scheduleSaveRef = useRef(null);

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
      toast.success(`Navixy : ${data.trips_new} nouveaux · ${data.trips_updated} màj`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Sync impossible");
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
      toast.success(sched.enabled ? `Sync auto activée toutes les ${data.interval_min} min` : "Sync auto désactivée");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Refusé");
    } finally { setSchedSaving(false); }
  }

  async function saveAll() {
    setSaving(true);
    try {
      // 1. politique
      await api.put("/livre/settings", { mode: settings.mode });
      // 2. plages horaires (delegated to ScheduleEditor via ref)
      if (scheduleSaveRef.current) {
        try { await scheduleSaveRef.current(); } catch { /* toast already shown */ }
      }
      // 3. scheduler config (if user changed values, persist)
      if (sched) {
        await api.put(`/livre/navixy/scheduler`, {
          enabled: sched.enabled, interval_min: sched.interval_min, days: sched.days,
        });
      }
      toast.success("Paramètres enregistrés");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Échec de l'enregistrement");
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

  return (
    <div data-testid={TEST_IDS.settings.page} className="space-y-5 animate-in fade-in slide-in-from-bottom-2 duration-300 max-w-[1320px]">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 flex items-center gap-2.5">
            <Shield className="w-5 h-5 text-[#2196F3]" /> Paramètres du livre de bord
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Politique de confidentialité, règles automatiques et modes véhicules
          </p>
        </div>
        <Button
          onClick={saveAll}
          disabled={!canEdit || saving}
          data-testid={TEST_IDS.settings.save}
          className="bg-[#2196F3] hover:bg-[#1E88E5] text-white shadow-sm"
        >
          {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
          Enregistrer les paramètres
        </Button>
      </div>

      {/* SECTION 1 — SYNCHRONISATION NAVIXY */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5">
        <SectionHeader n={1} title="Synchronisation Navixy"
          icon={navixy.configured ? Cloud : CloudOff}
          accent={navixy.configured ? "text-[#2196F3]" : "text-slate-400"} />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Auto */}
          <div className="border border-slate-200 rounded-md p-4 bg-slate-50/30">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-[180px]">
                <p className="text-xs font-semibold text-slate-800">Synchronisation automatique</p>
                <p className="text-[11px] text-slate-500 mt-1 leading-snug">
                  Lance une sync Navixy en arrière-plan à intervalle régulier.
                </p>
                {sched && (
                  <div className="mt-3 space-y-1 text-[11px] font-mono text-slate-600">
                    <p>Statut : <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${sched.enabled ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-slate-100 text-slate-600 border border-slate-200"}`}>
                      {sched.enabled ? "Activée" : "Désactivée"}
                    </span></p>
                    {sched.last_run && <p>Dernière exécution : {new Date(sched.last_run).toLocaleString("fr-CH")}</p>}
                    {sched.next_run && sched.enabled && <p>Prochaine : {new Date(sched.next_run).toLocaleString("fr-CH")}</p>}
                  </div>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Intervalle (min)</p>
                  <Input type="number" min="1" max="1440" value={sched?.interval_min || 15}
                    onChange={(e) => setSched({ ...sched, interval_min: parseInt(e.target.value, 10) || 15 })}
                    disabled={user?.role !== "admin"} data-testid="settings-sched-interval"
                    className="h-9 w-20" />
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Période (jours)</p>
                  <Input type="number" min="1" max="365" value={sched?.days || 7}
                    onChange={(e) => setSched({ ...sched, days: parseInt(e.target.value, 10) || 7 })}
                    disabled={user?.role !== "admin"} data-testid="settings-sched-days"
                    className="h-9 w-20" />
                </div>
                <div className="col-span-2 flex items-center justify-between pt-1">
                  <div className="flex items-center gap-2">
                    <Switch
                      checked={!!sched?.enabled}
                      disabled={user?.role !== "admin" || !navixy.configured}
                      data-testid="settings-sched-toggle"
                      onCheckedChange={(v) => { setSched({ ...sched, enabled: v }); }}
                    />
                    <span className="text-xs text-slate-700 flex items-center gap-1.5">
                      <Power className="w-3 h-3" /> {sched?.enabled ? "Activée" : "Désactivée"}
                    </span>
                  </div>
                  <Button size="sm" variant="outline" onClick={saveScheduler}
                    disabled={user?.role !== "admin" || schedSaving} data-testid="settings-sched-save"
                    className="h-7 text-[11px] px-2">
                    {schedSaving ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
                    Appliquer
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* Manuel */}
          <div className="border border-slate-200 rounded-md p-4 bg-slate-50/30">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="flex-1 min-w-[180px]">
                <p className="text-xs font-semibold text-slate-800">Sync manuelle</p>
                <p className="text-[11px] text-slate-500 mt-1 leading-snug">
                  Synchronise immédiatement les véhicules, chauffeurs, zones et trajets.
                </p>
              </div>
              <div className="flex items-end gap-2">
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Période (jours)</p>
                  <Input type="number" min="1" max="365"
                    disabled={!navixy.configured || syncing || user?.role !== "admin"}
                    value={syncDays} onChange={(e) => setSyncDays(parseInt(e.target.value, 10) || 30)}
                    data-testid="settings-navixy-days" className="w-20 h-9" />
                </div>
                <Button
                  disabled={!navixy.configured || syncing || user?.role !== "admin"}
                  onClick={syncNavixy} data-testid="settings-navixy-sync"
                  className="bg-[#2196F3] hover:bg-[#1E88E5] text-white h-9">
                  {syncing ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
                  Synchroniser
                </Button>
              </div>
            </div>
            <p className="text-[10px] text-slate-500 mt-3 bg-blue-50 border border-blue-100 rounded px-2 py-1.5 leading-snug">
              💡 La synchronisation importe les véhicules <span className="font-mono">tracker/list</span>, les chauffeurs <span className="font-mono">employee/list</span>, les zones <span className="font-mono">zone/list</span> et les trajets <span className="font-mono">track/list</span>.
            </p>
            {lastSync && (
              <p className="text-[10px] font-mono text-slate-600 mt-2">
                ✓ {lastSync.trackers} véhicules · {lastSync.trips_new} nouveaux · {lastSync.trips_updated} màj
              </p>
            )}
          </div>
        </div>
      </Card>

      {/* SECTION 2 — POLITIQUE DE CONFIDENTIALITÉ */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5">
        <SectionHeader n={2} title="Politique de confidentialité"
          subtitle="Détermine ce que voient les gestionnaires des trajets personnels. Le mode « 100 % professionnel » est désormais configuré par véhicule." />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {MODE_OPTIONS.map(opt => {
            const active = settings.mode === opt.id;
            const Icon = opt.icon;
            return (
              <button
                key={opt.id} type="button" data-testid={opt.testId}
                disabled={!canEdit}
                onClick={() => setSettings({ ...settings, mode: opt.id })}
                className={`text-left rounded-md border p-4 transition-all flex flex-col min-h-[120px] ${
                  active
                    ? "border-[#2196F3] bg-blue-50 ring-2 ring-[#2196F3]/20"
                    : "border-slate-200 hover:border-slate-300 bg-white"
                } ${!canEdit ? "opacity-60 cursor-not-allowed" : ""}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Icon className={`w-4 h-4 ${active ? "text-[#2196F3]" : "text-slate-400"}`} />
                    <span className={`text-sm font-semibold ${active ? "text-[#1976D2]" : "text-slate-800"}`}>
                      {opt.label}
                    </span>
                  </div>
                  <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${
                    active && opt.id === "mixte"  ? "bg-emerald-50 text-emerald-700 border-emerald-300" :
                    active && opt.id === "masked" ? "bg-blue-100 text-blue-700 border-blue-300" :
                    "bg-slate-100 text-slate-500 border-slate-200"
                  }`}>
                    {active ? "Actif" : opt.badge}
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 leading-relaxed flex-1">{opt.desc}</p>
              </button>
            );
          })}
        </div>
      </Card>

      {/* SECTION 3 — PLAGES HORAIRES PRO */}
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5">
        <SectionHeader n={3} title="Plages horaires professionnelles"
          icon={Calendar}
          subtitle="Définissez pour chaque jour jusqu'à 3 plages horaires considérées comme professionnelles. Le reste de la journée est automatiquement personnel." />
        <ScheduleEditor canEdit={canEdit} drivers={drivers}
          registerSave={(fn) => { scheduleSaveRef.current = fn; }} />
      </Card>

      {/* SECTION 4 — MODE PRIVÉ TRACEURS */}
      {canEdit && (
        <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5">
          <div className="grid grid-cols-1 lg:grid-cols-10 gap-5">
            {/* LEFT 70% — Compatibility scan */}
            <div className="lg:col-span-7">
              <SectionHeader n={4} title="Mode privé des traceurs (Confidentialité à la source)"
                icon={ShieldCheck}
                subtitle="Phase 1 — Scan en lecture seule. Aucune commande n'est envoyée aux traceurs. Identification des traceurs compatibles avec le mode privé (privacy mode)." />
              <PrivacyCompatCard />
            </div>
            {/* RIGHT 30% — Enforcement */}
            <div className="lg:col-span-3 lg:border-l lg:border-slate-200 lg:pl-5">
              <div className="mb-4">
                <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
                  <Power className="w-4 h-4 text-emerald-600" /> Enforcement du mode privé (Phase 2)
                </h2>
                <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">
                  Envoie automatiquement les commandes <span className="font-mono">setparam 11000:0/4</span> aux traceurs Teltonika compatibles, toutes les 5 min.
                </p>
              </div>
              <PrivacyEnforcementCard />
            </div>
          </div>
        </Card>
      )}

      {/* Footer — gestion véhicules (slide-over) */}
      <div className="pt-1 flex justify-end">
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="outline" size="sm" data-testid="open-vehicles-sheet">
              <Truck className="w-3.5 h-3.5 mr-1.5" /> Gérer les véhicules & affectations ({vehicles.length})
            </Button>
          </SheetTrigger>
          <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto">
            <SheetHeader>
              <SheetTitle className="text-base font-semibold flex items-center gap-2">
                <Truck className="w-4 h-4 text-slate-500" /> Modes véhicules & affectations
              </SheetTitle>
              <p className="text-xs text-slate-500">
                Forçage de classification par véhicule (mixte / 100 % pro / 100 % perso) et affectations chauffeurs.
              </p>
            </SheetHeader>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 text-slate-500 text-[10px] font-semibold uppercase tracking-wider">
                    <th className="text-left py-2.5 px-3">Plaque</th>
                    <th className="text-left py-2.5 px-3">Modèle</th>
                    <th className="text-right py-2.5 px-3">Mode</th>
                    <th className="text-right py-2.5 px-3">Affectations</th>
                  </tr>
                </thead>
                <tbody>
                  {vehicles.map(v => (
                    <tr key={v.id} className="border-t border-slate-100">
                      <td className="py-2.5 px-3 font-mono text-xs">{v.plate}</td>
                      <td className="py-2.5 px-3 text-slate-700 text-xs">{v.model}</td>
                      <td className="py-2.5 px-3 text-right">
                        <Select value={v.mode} onValueChange={(val) => changeVehicleMode(v.id, val)} disabled={!canEdit}>
                          <SelectTrigger className="w-40 ml-auto h-8 text-xs"
                            data-testid={`${TEST_IDS.settings.vehicleModeSelect}-${v.plate.replace(/\s+/g, "-")}`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="mixte">Mixte</SelectItem>
                            <SelectItem value="always_pro">100 % Professionnel</SelectItem>
                            <SelectItem value="always_perso">100 % Personnel</SelectItem>
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <AssignmentsDialog vehicle={v} drivers={drivers} canEdit={canEdit} onChanged={load} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  );
}
