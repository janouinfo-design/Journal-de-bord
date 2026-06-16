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
import { Shield, Eye, EyeOff, Briefcase, Loader2, Save, Truck } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

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
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [s, v] = await Promise.all([
        api.get("/livre/settings").then(r => r.data),
        api.get("/livre/vehicles").then(r => r.data),
      ]);
      setSettings(s); setVehicles(v);
    } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

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
          <Truck className="w-4 h-4 text-slate-500" /> Modes véhicules
        </h3>
        <p className="text-xs text-slate-500 mb-5">Forçage de classification par véhicule.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs font-medium uppercase tracking-wider">
                <th className="text-left py-3 px-4">Plaque</th>
                <th className="text-left py-3 px-4">Modèle</th>
                <th className="text-right py-3 px-4">Mode</th>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
