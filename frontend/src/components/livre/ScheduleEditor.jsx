import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { toast } from "sonner";
import { Loader2, RotateCcw, Copy, Info } from "lucide-react";
import DayTimeline from "@/components/livre/DayTimeline";

const DAYS_FR = [
  { idx: 0, label: "Lundi" },
  { idx: 1, label: "Mardi" },
  { idx: 2, label: "Mercredi" },
  { idx: 3, label: "Jeudi" },
  { idx: 4, label: "Vendredi" },
  { idx: 5, label: "Samedi" },
  { idx: 6, label: "Dimanche" },
];

function blankPeriods() {
  return [
    { enabled: false, from: "08:00", to: "12:00" },
    { enabled: false, from: "13:30", to: "17:00" },
    { enabled: false, from: "00:00", to: "00:00" },
  ];
}

function ensureDays(days) {
  if (!Array.isArray(days)) return DAYS_FR.map((d) => ({ day: d.idx, type: "work", periods: blankPeriods() }));
  return DAYS_FR.map((d) => {
    const found = days.find((x) => x.day === d.idx);
    if (found) {
      const periods = (found.periods || []).slice(0, 3);
      while (periods.length < 3) periods.push({ enabled: false, from: "00:00", to: "00:00" });
      return { day: d.idx, type: found.type || "work", periods };
    }
    return { day: d.idx, type: "work", periods: blankPeriods() };
  });
}

export default function ScheduleEditor({ canEdit, drivers, registerSave }) {
  const [scope, setScope] = useState("all");
  const [driverId, setDriverId] = useState("");
  const [days, setDays] = useState(ensureDays(null));
  const [loading, setLoading] = useState(true);

  async function load(targetDriverId) {
    setLoading(true);
    try {
      const url = targetDriverId
        ? `/livre/schedule?driver_id=${encodeURIComponent(targetDriverId)}`
        : `/livre/schedule`;
      const { data } = await api.get(url);
      setDays(ensureDays(data.days));
    } finally { setLoading(false); }
  }
  useEffect(() => { load(null); }, []);

  function changeScope(next) {
    setScope(next);
    if (next === "all") { setDriverId(""); load(null); }
    else if (drivers.length) { const first = drivers[0].id; setDriverId(first); load(first); }
  }

  function setDayField(idx, patch) {
    setDays((prev) => prev.map((d) => (d.day === idx ? { ...d, ...patch } : d)));
  }
  function setPeriod(dayIdx, pIdx, patch) {
    setDays((prev) => prev.map((d) =>
      d.day === dayIdx
        ? { ...d, periods: d.periods.map((p, i) => (i === pIdx ? { ...p, ...patch } : p)) }
        : d,
    ));
  }

  function copyMondayToWeekdays() {
    const monday = days.find((d) => d.day === 0);
    if (!monday) return;
    setDays((prev) => prev.map((d) =>
      d.day >= 1 && d.day <= 4
        ? { ...d, type: monday.type, periods: monday.periods.map((p) => ({ ...p })) }
        : d,
    ));
    toast.success("Lundi copié sur Mar → Ven");
  }

  async function save() {
    try {
      await api.put(`/livre/schedule`, {
        driver_id: scope === "specific" ? driverId : null,
        days,
      });
      toast.success("Plages horaires enregistrées · règles réappliquées");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Refusé");
      throw e;
    }
  }
  useEffect(() => { if (registerSave) registerSave(save); /* eslint-disable-next-line */ }, [days, scope, driverId]);

  async function resetToDefault() {
    if (scope !== "specific" || !driverId) return;
    try {
      await api.delete(`/livre/schedule?driver_id=${encodeURIComponent(driverId)}`);
      toast.success("Override supprimé");
      load(null); setScope("all"); setDriverId("");
    } catch { toast.error("Refusé"); }
  }

  return (
    <div className="grid grid-cols-12 gap-5">
      {/* LEFT — driver & model selector */}
      <aside className="col-span-12 lg:col-span-3 space-y-5">
        <div className="bg-slate-50 border border-slate-200 rounded-md p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-3">
            Sélectionner le chauffeur
          </p>
          <RadioGroup value={scope} onValueChange={changeScope} className="space-y-2.5">
            <div className="flex items-center gap-2">
              <RadioGroupItem value="all" id="scope-all" data-testid="schedule-scope-all" disabled={!canEdit} />
              <Label htmlFor="scope-all" className="text-sm text-slate-700 cursor-pointer">Tous les chauffeurs</Label>
            </div>
            <div className="flex items-center gap-2">
              <RadioGroupItem value="specific" id="scope-specific" data-testid="schedule-scope-specific" disabled={!canEdit || drivers.length === 0} />
              <Label htmlFor="scope-specific" className="text-sm text-slate-700 cursor-pointer">Chauffeur spécifique</Label>
            </div>
          </RadioGroup>
          {scope === "specific" && (
            <div className="mt-3 space-y-2">
              <Select value={driverId} onValueChange={(v) => { setDriverId(v); load(v); }} disabled={!canEdit}>
                <SelectTrigger data-testid="schedule-driver-select" className="w-full">
                  <SelectValue placeholder="Choisir un chauffeur" />
                </SelectTrigger>
                <SelectContent>
                  {drivers.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                </SelectContent>
              </Select>
              {driverId && (
                <Button variant="ghost" size="sm" onClick={resetToDefault}
                  data-testid="schedule-reset-override"
                  className="text-xs text-red-600 hover:text-red-700 h-8 -ml-2">
                  <RotateCcw className="w-3 h-3 mr-1" /> Revenir au planning par défaut
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="bg-slate-50 border border-slate-200 rounded-md p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-3">
            Type de jour
          </p>
          <Select value="info" disabled>
            <SelectTrigger className="w-full text-xs">
              <SelectValue placeholder="Journée de travail" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="info">Journée de travail</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-[11px] text-slate-500 mt-3 leading-relaxed flex gap-1.5">
            <Info className="w-3.5 h-3.5 text-slate-400 mt-0.5 shrink-0" />
            Astuce : configurez lundi, puis appliquez le modèle à toute la semaine.
          </p>
          <Button variant="outline" size="sm" disabled={!canEdit}
            onClick={copyMondayToWeekdays} data-testid="schedule-copy-monday"
            className="text-xs h-8 mt-3 w-full">
            <Copy className="w-3.5 h-3.5 mr-1.5" /> Copier lundi sur Mar → Ven
          </Button>
        </div>
      </aside>

      {/* RIGHT — compact table */}
      <div className="col-span-12 lg:col-span-9 overflow-x-auto">
        {loading ? (
          <div className="py-10 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div>
        ) : (
          <>
            <table className="w-full text-sm" data-testid="schedule-table">
              <thead>
                <tr className="text-slate-500 text-[10px] uppercase tracking-wider border-b border-slate-200">
                  <th className="text-left py-2 pr-2 font-semibold">Jour</th>
                  <th className="text-left py-2 px-2 font-semibold">Période 1</th>
                  <th className="text-left py-2 px-2 font-semibold">Période 2</th>
                  <th className="text-left py-2 px-2 font-semibold">Période 3 (optionnelle)</th>
                  <th className="text-left py-2 pl-3 font-semibold w-[24%]">Aperçu</th>
                </tr>
              </thead>
              <tbody>
                {DAYS_FR.map((d) => {
                  const cfg = days.find((x) => x.day === d.idx) || { type: "work", periods: blankPeriods() };
                  const dayChecked = cfg.type === "work" && cfg.periods.some(p => p.enabled);
                  return (
                    <tr key={d.idx} data-testid={`schedule-day-${d.idx}`} className="border-b border-slate-100 last:border-b-0 align-middle">
                      <td className="py-2.5 pr-2">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <Checkbox
                            checked={dayChecked}
                            disabled={!canEdit}
                            data-testid={`schedule-day-checkbox-${d.idx}`}
                            onCheckedChange={(v) => {
                              if (v) {
                                // enable as work + ensure period 1 enabled
                                const periods = cfg.periods.map((p, i) =>
                                  i === 0 ? { ...p, enabled: true, from: p.from || "08:00", to: p.to || "12:00" } : p);
                                setDayField(d.idx, { type: "work", periods });
                              } else {
                                setDayField(d.idx, { type: "personal" });
                              }
                            }}
                            className="data-[state=checked]:bg-[#2196F3] data-[state=checked]:border-[#2196F3]"
                          />
                          <span className="text-sm font-medium text-slate-800">{d.label}</span>
                        </label>
                      </td>
                      {cfg.periods.map((p, i) => (
                        <td key={i} className="py-2.5 px-2">
                          <PeriodCell
                            period={p}
                            dayIdx={d.idx}
                            pIdx={i}
                            disabled={!canEdit || cfg.type === "personal"}
                            onChange={(patch) => setPeriod(d.idx, i, patch)}
                          />
                        </td>
                      ))}
                      <td className="py-2.5 pl-3">
                        <DayTimeline periods={cfg.periods} dayType={cfg.type} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className="flex items-center gap-4 mt-3 text-[11px] text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm bg-[#2196F3]"></span> Plage professionnelle
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-3 rounded-sm bg-slate-200 border border-slate-300"></span> Plage personnelle
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function PeriodCell({ period, dayIdx, pIdx, disabled, onChange }) {
  return (
    <div className={`flex items-center gap-1.5 ${period.enabled ? "" : "opacity-50"}`}>
      <Checkbox
        checked={period.enabled}
        disabled={disabled}
        data-testid={`schedule-period-enable-${dayIdx}-${pIdx}`}
        onCheckedChange={(v) => onChange({ enabled: !!v })}
        className="data-[state=checked]:bg-[#2196F3] data-[state=checked]:border-[#2196F3] shrink-0"
      />
      <span className="text-[10px] text-slate-400 shrink-0">De</span>
      <Input type="time" value={period.from} disabled={disabled || !period.enabled}
        onChange={(e) => onChange({ from: e.target.value })}
        data-testid={`schedule-period-from-${dayIdx}-${pIdx}`}
        className="w-[78px] h-8 px-2 text-xs" />
      <span className="text-[10px] text-slate-400 shrink-0">à</span>
      <Input type="time" value={period.to} disabled={disabled || !period.enabled}
        onChange={(e) => onChange({ to: e.target.value })}
        data-testid={`schedule-period-to-${dayIdx}-${pIdx}`}
        className="w-[78px] h-8 px-2 text-xs" />
    </div>
  );
}
