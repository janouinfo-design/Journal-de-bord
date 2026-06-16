import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { toast } from "sonner";
import { Save, Loader2, RotateCcw, Calendar, Copy } from "lucide-react";
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
    { enabled: false, from: "08:00", to: "17:00" },
    { enabled: false, from: "08:00", to: "17:00" },
    { enabled: false, from: "08:00", to: "17:00" },
  ];
}

function ensureDays(days) {
  if (!Array.isArray(days)) return DAYS_FR.map((d) => ({ day: d.idx, type: "work", periods: blankPeriods() }));
  return DAYS_FR.map((d) => {
    const found = days.find((x) => x.day === d.idx);
    if (found) {
      const periods = (found.periods || []).slice(0, 3);
      while (periods.length < 3) periods.push({ enabled: false, from: "08:00", to: "17:00" });
      return { day: d.idx, type: found.type || "work", periods };
    }
    return { day: d.idx, type: "work", periods: blankPeriods() };
  });
}

export default function ScheduleEditor({ canEdit, drivers }) {
  const [scope, setScope] = useState("all"); // 'all' | 'specific'
  const [driverId, setDriverId] = useState("");
  const [days, setDays] = useState(ensureDays(null));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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

  useEffect(() => { load(null); /* default */ }, []);

  function changeScope(next) {
    setScope(next);
    if (next === "all") {
      setDriverId("");
      load(null);
    } else if (drivers.length) {
      const firstId = drivers[0].id;
      setDriverId(firstId);
      load(firstId);
    }
  }

  function setDayField(idx, patch) {
    setDays((prev) => prev.map((d) => (d.day === idx ? { ...d, ...patch } : d)));
  }

  function setPeriod(dayIdx, pIdx, patch) {
    setDays((prev) =>
      prev.map((d) =>
        d.day === dayIdx
          ? { ...d, periods: d.periods.map((p, i) => (i === pIdx ? { ...p, ...patch } : p)) }
          : d,
      ),
    );
  }

  function copyMondayToWeekdays() {
    const monday = days.find((d) => d.day === 0);
    if (!monday) return;
    setDays((prev) =>
      prev.map((d) =>
        d.day >= 1 && d.day <= 4
          ? {
              ...d,
              type: monday.type,
              periods: monday.periods.map((p) => ({ ...p })),
            }
          : d,
      ),
    );
    toast.success("Lundi copié sur Mar → Ven");
  }

  async function save() {
    setSaving(true);
    try {
      await api.put(`/livre/schedule`, {
        driver_id: scope === "specific" ? driverId : null,
        days,
      });
      toast.success("Planning enregistré · règles réappliquées");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Refusé");
    } finally { setSaving(false); }
  }

  async function resetToDefault() {
    if (scope !== "specific" || !driverId) return;
    try {
      await api.delete(`/livre/schedule?driver_id=${encodeURIComponent(driverId)}`);
      toast.success("Override supprimé — planning par défaut restauré");
      load(null);
      setScope("all");
      setDriverId("");
    } catch { toast.error("Refusé"); }
  }

  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-md p-6">
      <div className="flex items-start justify-between flex-wrap gap-4 mb-5">
        <div>
          <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <Calendar className="w-4 h-4 text-[#2196F3]" /> Plages horaires professionnelles
          </h3>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl leading-relaxed">
            Définissez pour chaque jour jusqu'à <b>3 plages horaires</b> considérées comme professionnelles.
            Le reste de la journée est automatiquement <b>personnel</b>. Choisissez « Routes personnelles »
            pour qu'un jour entier soit personnel.
          </p>
        </div>
      </div>

      {/* Scope selector */}
      <div className="bg-slate-50 border border-slate-200 rounded-md p-4 mb-6">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-3">Sélectionner le chauffeur</p>
        <RadioGroup
          value={scope}
          onValueChange={changeScope}
          className="flex flex-wrap items-center gap-6"
        >
          <div className="flex items-center gap-2">
            <RadioGroupItem
              value="all" id="scope-all"
              data-testid="schedule-scope-all"
              disabled={!canEdit}
            />
            <Label htmlFor="scope-all" className="text-sm text-slate-700 cursor-pointer">Tous les chauffeurs</Label>
          </div>
          <div className="flex items-center gap-2">
            <RadioGroupItem
              value="specific" id="scope-specific"
              data-testid="schedule-scope-specific"
              disabled={!canEdit || drivers.length === 0}
            />
            <Label htmlFor="scope-specific" className="text-sm text-slate-700 cursor-pointer">Chauffeur spécifique</Label>
          </div>
          {scope === "specific" && (
            <div className="flex items-center gap-3">
              <Select
                value={driverId}
                onValueChange={(v) => { setDriverId(v); load(v); }}
                disabled={!canEdit}
              >
                <SelectTrigger
                  data-testid="schedule-driver-select"
                  className="w-64"
                >
                  <SelectValue placeholder="Choisir un chauffeur" />
                </SelectTrigger>
                <SelectContent>
                  {drivers.map((d) => (
                    <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {driverId && (
                <Button
                  variant="ghost" size="sm"
                  onClick={resetToDefault}
                  data-testid="schedule-reset-override"
                  className="text-xs text-red-600 hover:text-red-700 h-8"
                >
                  <RotateCcw className="w-3 h-3 mr-1" /> Revenir au planning par défaut
                </Button>
              )}
            </div>
          )}
        </RadioGroup>

        <div className="mt-4 pt-4 border-t border-slate-200 flex items-center justify-between flex-wrap gap-2">
          <p className="text-xs text-slate-500">
            Astuce : configurez Lundi, puis appliquez-le à toute la semaine de travail en un clic.
          </p>
          <Button
            variant="outline" size="sm"
            disabled={!canEdit}
            onClick={copyMondayToWeekdays}
            data-testid="schedule-copy-monday"
            className="text-xs h-8"
          >
            <Copy className="w-3.5 h-3.5 mr-1.5" /> Copier Lundi sur Mar → Ven
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="py-16 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
      ) : (
        <div className="space-y-6">
          {DAYS_FR.map((d) => {
            const dayCfg = days.find((x) => x.day === d.idx) || { type: "work", periods: blankPeriods() };
            return (
              <div
                key={d.idx}
                data-testid={`schedule-day-${d.idx}`}
                className="grid grid-cols-12 gap-4 pb-6 border-b border-slate-100 last:border-b-0"
              >
                <div className="col-span-12 md:col-span-3">
                  <p className="font-semibold text-slate-800 text-base">{d.label}</p>
                  <Select
                    value={dayCfg.type}
                    onValueChange={(v) => setDayField(d.idx, { type: v })}
                    disabled={!canEdit}
                  >
                    <SelectTrigger
                      data-testid={`schedule-day-type-${d.idx}`}
                      className="mt-2 w-full max-w-[220px]"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="work">Journée de travail</SelectItem>
                      <SelectItem value="personal">Routes personnelles</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="col-span-12 md:col-span-9 space-y-2.5">
                  {dayCfg.type === "personal" ? (
                    <p className="text-sm text-slate-500 italic mt-2 bg-slate-50 border border-slate-200 rounded-md px-3 py-2">
                      Jour entièrement considéré comme personnel.
                    </p>
                  ) : (
                    dayCfg.periods.map((p, i) => (
                      <div
                        key={i}
                        data-testid={`schedule-period-${d.idx}-${i}`}
                        className={`flex items-center flex-wrap gap-3 rounded-md px-3 py-2 transition-colors ${
                          p.enabled ? "bg-blue-50/40 border border-blue-100" : "bg-slate-50/50 border border-transparent"
                        }`}
                      >
                        <Checkbox
                          checked={p.enabled}
                          disabled={!canEdit}
                          data-testid={`schedule-period-enable-${d.idx}-${i}`}
                          onCheckedChange={(v) => setPeriod(d.idx, i, { enabled: !!v })}
                          className="data-[state=checked]:bg-[#2196F3] data-[state=checked]:border-[#2196F3]"
                        />
                        <span className="text-sm text-slate-700 w-20">{i + 1}. Période</span>
                        <Label className="text-xs text-slate-500">De</Label>
                        <Input
                          type="time"
                          value={p.from}
                          disabled={!canEdit || !p.enabled}
                          data-testid={`schedule-period-from-${d.idx}-${i}`}
                          onChange={(e) => setPeriod(d.idx, i, { from: e.target.value })}
                          className="w-28 h-9"
                        />
                        <Label className="text-xs text-slate-500">à</Label>
                        <Input
                          type="time"
                          value={p.to}
                          disabled={!canEdit || !p.enabled}
                          data-testid={`schedule-period-to-${d.idx}-${i}`}
                          onChange={(e) => setPeriod(d.idx, i, { to: e.target.value })}
                          className="w-28 h-9"
                        />
                      </div>
                    ))
                  )}

                  {/* 0-24h visual timeline */}
                  <div className="pt-2" data-testid={`schedule-timeline-${d.idx}`}>
                    <DayTimeline periods={dayCfg.periods} dayType={dayCfg.type} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-6 pt-6 border-t border-slate-100 flex justify-end">
        <Button
          disabled={!canEdit || saving}
          onClick={save}
          data-testid="schedule-save"
          className="bg-[#2196F3] hover:bg-[#1E88E5] text-white"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Save className="w-4 h-4 mr-2" />}
          Enregistrer les paramètres
        </Button>
      </div>
    </Card>
  );
}
