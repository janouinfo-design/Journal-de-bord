import { useEffect, useMemo, useState } from "react";
import { api, fmtKm, fmtDateTime, fmtDuration, downloadBlob } from "@/lib/api";
import { TEST_IDS } from "@/constants/testIds";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ClassificationBadge } from "@/components/livre/Badges";
import { toast } from "sonner";
import {
  Loader2, ArrowLeftRight, Briefcase, User, EyeOff, Gauge,
  MapPin, Fuel, Clock, Calendar, FileText, FileSpreadsheet, FileDown,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

export default function HistoryPage({ kind }) {
  const { user } = useAuth();
  const [trips, setTrips] = useState([]);
  const [mode, setMode] = useState("A");
  const [loading, setLoading] = useState(true);
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [filters, setFilters] = useState({ driver_id: "all", vehicle_id: "all", start: "", end: "" });

  async function fetchAll() {
    setLoading(true);
    try {
      const params = { classification: kind === "pro" ? "professional" : "personal" };
      if (filters.driver_id && filters.driver_id !== "all") params.driver_id = filters.driver_id;
      if (filters.vehicle_id && filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
      if (filters.start) params.start = new Date(filters.start).toISOString();
      if (filters.end) params.end = new Date(filters.end).toISOString();
      const { data } = await api.get("/livre/trips", { params });
      setTrips(data.trips);
      setMode(data.settings_mode);
    } finally { setLoading(false); }
  }

  useEffect(() => {
    (async () => {
      const [d, v] = await Promise.all([
        api.get("/livre/drivers").then(r => r.data),
        api.get("/livre/vehicles").then(r => r.data),
      ]);
      setDrivers(d); setVehicles(v);
    })();
  }, []);

  useEffect(() => { fetchAll(); /* eslint-disable-next-line */ }, [kind, filters]);

  async function classify(trip, target) {
    try {
      await api.put(`/livre/trips/${trip.id}/classify`, { classification: target });
      toast.success(target === "professional" ? "Trajet → Professionnel" : "Trajet → Personnel");
      fetchAll();
    } catch (e) {
      toast.error("Modification refusée");
    }
  }

  async function exportReport(fmt) {
    try {
      const params = {
        classification: kind === "pro" ? "professional" : "personal",
        fmt,
      };
      if (filters.driver_id && filters.driver_id !== "all") params.driver_id = filters.driver_id;
      if (filters.vehicle_id && filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
      if (filters.start) params.start = new Date(filters.start).toISOString();
      if (filters.end) params.end = new Date(filters.end).toISOString();
      const res = await api.get("/livre/reports/export", { params, responseType: "blob" });
      downloadBlob(res.data, `rapport_${kind}_${Date.now()}.${fmt}`);
      toast.success(`Export ${fmt.toUpperCase()} prêt`);
    } catch (e) {
      toast.error("Export impossible");
    }
  }

  const isMasked = kind === "perso" && mode === "masked" && user?.role !== "admin";
  const canEdit = user?.role === "admin" || user?.role === "manager";

  // KPI totals for masked perso view (computed via /dashboard which gives pct & km totals)
  const [maskedSummary, setMaskedSummary] = useState(null);
  useEffect(() => {
    if (!isMasked) { setMaskedSummary(null); return; }
    (async () => {
      try {
        const params = {};
        if (filters.start) params.start = new Date(filters.start).toISOString();
        if (filters.end) params.end = new Date(filters.end).toISOString();
        if (filters.driver_id && filters.driver_id !== "all") params.driver_id = filters.driver_id;
        if (filters.vehicle_id && filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
        const { data } = await api.get("/livre/dashboard", { params });
        setMaskedSummary(data.kpi);
      } catch { setMaskedSummary(null); }
    })();
  }, [isMasked, filters]);

  const stats = useMemo(() => {
    const km = trips.reduce((s, t) => s + (t.distance_km || 0), 0);
    const min = trips.reduce((s, t) => s + (t.duration_min || 0), 0);
    return { count: trips.length, km, min };
  }, [trips]);

  return (
    <div data-testid={TEST_IDS.history.page} className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Historique</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900 mt-1 flex items-center gap-3">
            {kind === "pro" ? <Briefcase className="w-6 h-6 text-[#2196F3]" /> : <User className="w-6 h-6 text-slate-500" />}
            {kind === "pro" ? "Historique professionnel" : "Historique personnel"}
          </h1>
          <p className="text-sm text-slate-500 mt-1.5">
            {kind === "pro"
              ? "Tous les trajets classifiés professionnels."
              : isMasked
                ? "Mode Personnel Masqué — confidentialité totale : ni dates, ni adresses, ni durées, ni vitesses."
                : "Trajets personnels — chauffeur, dates, lieux et carte."}
          </p>
        </div>
        {!isMasked && (
          <div className="flex gap-2 text-sm">
            <div className="bg-white border border-slate-200 rounded-md px-3 py-2">
              <p className="text-[10px] uppercase text-slate-400 tracking-wider">Total km</p>
              <p className="font-semibold text-slate-800">{fmtKm(stats.km)}</p>
            </div>
            <div className="bg-white border border-slate-200 rounded-md px-3 py-2">
              <p className="text-[10px] uppercase text-slate-400 tracking-wider">Trajets</p>
              <p className="font-semibold text-slate-800">{stats.count}</p>
            </div>
            <div className="bg-white border border-slate-200 rounded-md px-3 py-2">
              <p className="text-[10px] uppercase text-slate-400 tracking-wider">Durée</p>
              <p className="font-semibold text-slate-800">{fmtDuration(stats.min)}</p>
            </div>
          </div>
        )}
      </div>

      {isMasked && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-md px-4 py-3 flex items-center gap-2 text-sm">
          <EyeOff className="w-4 h-4" />
          Mode Personnel Masqué : la liste des trajets, la carte, les dates, les adresses et toute donnée individuelle sont masquées. Seuls les totaux agrégés sont visibles.
        </div>
      )}

      {/* Masked view: ONLY total km + percentage — nothing else */}
      {isMasked ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl">
          <Card data-testid="masked-total-km" className="bg-white border-slate-200 shadow-sm rounded-md p-6">
            <p className="text-xs font-semibold tracking-wider uppercase text-slate-500">Total km personnels</p>
            <p className="mt-3 text-4xl font-semibold text-slate-700 tracking-tight">
              {maskedSummary ? fmtKm(maskedSummary.perso_km) : "—"}
            </p>
            <p className="text-xs text-slate-400 mt-2">
              Période : {filters.start || "depuis l'origine"} → {filters.end || "aujourd'hui"}
            </p>
          </Card>
          <Card data-testid="masked-pct" className="bg-white border-slate-200 shadow-sm rounded-md p-6">
            <p className="text-xs font-semibold tracking-wider uppercase text-slate-500">% personnel</p>
            <p className="mt-3 text-4xl font-semibold text-slate-700 tracking-tight">
              {maskedSummary ? `${maskedSummary.pct_perso.toFixed(1)} %` : "—"}
            </p>
            <p className="text-xs text-slate-400 mt-2">
              Part du kilométrage privé sur la période
            </p>
          </Card>
        </div>
      ) : (
      <>
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4">
        <div className="flex items-end justify-between gap-3 flex-wrap">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 flex-1">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Chauffeur</p>
              <Select value={filters.driver_id} onValueChange={(v) => setFilters({ ...filters, driver_id: v })}>
                <SelectTrigger data-testid={TEST_IDS.history.filterDriver}><SelectValue placeholder="Tous" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tous les chauffeurs</SelectItem>
                  {drivers.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Véhicule</p>
              <Select value={filters.vehicle_id} onValueChange={(v) => setFilters({ ...filters, vehicle_id: v })}>
                <SelectTrigger data-testid={TEST_IDS.history.filterVehicle}><SelectValue placeholder="Tous" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Tous les véhicules</SelectItem>
                  {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.plate} — {v.model}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Du</p>
              <Input type="date" data-testid={TEST_IDS.history.filterStart}
                value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value })} />
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Au</p>
              <Input type="date" data-testid={TEST_IDS.history.filterEnd}
                value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value })} />
            </div>
          </div>
        </div>
        <div className="mt-4 pt-4 border-t border-slate-100 flex items-center justify-between flex-wrap gap-2">
          <p className="text-xs text-slate-500">
            Export selon les filtres ci-dessus · {trips.length} trajet{trips.length > 1 ? "s" : ""} concernés.
          </p>
          <div className="flex gap-2">
            <Button
              size="sm" onClick={() => exportReport("pdf")}
              data-testid={TEST_IDS.reports.btnPdf}
              className="bg-[#2196F3] hover:bg-[#1E88E5] text-white"
            >
              <FileText className="w-4 h-4 mr-1.5" /> Télécharger PDF
            </Button>
            <Button
              size="sm" variant="outline" onClick={() => exportReport("xlsx")}
              data-testid={TEST_IDS.reports.btnXlsx}
            >
              <FileSpreadsheet className="w-4 h-4 mr-1.5" /> Excel
            </Button>
            <Button
              size="sm" variant="outline" onClick={() => exportReport("csv")}
              data-testid={TEST_IDS.reports.btnCsv}
            >
              <FileDown className="w-4 h-4 mr-1.5" /> CSV
            </Button>
          </div>
        </div>
      </Card>

      <Card className="bg-white border-slate-200 shadow-sm rounded-md overflow-hidden">
        {loading ? (
          <div className="py-16 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
        ) : trips.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-sm">Aucun trajet sur cette période.</div>
        ) : (
          <div className="overflow-x-auto">
            <table data-testid={TEST_IDS.history.table} className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 text-slate-500 text-xs font-medium uppercase tracking-wider">
                  <th className="text-left py-3 px-5">Date</th>
                  <th className="text-left py-3 px-4">Chauffeur</th>
                  <th className="text-left py-3 px-4">Véhicule</th>
                  {!isMasked && <th className="text-left py-3 px-4">Départ → Arrivée</th>}
                  <th className="text-right py-3 px-4">Distance</th>
                  <th className="text-right py-3 px-4">Durée</th>
                  {!isMasked && <th className="text-right py-3 px-4">Carb.</th>}
                  {!isMasked && <th className="text-right py-3 px-4">Vit. max</th>}
                  <th className="text-center py-3 px-4">Type</th>
                  {canEdit && <th className="text-right py-3 px-5">Affectation</th>}
                </tr>
              </thead>
              <tbody>
                {trips.map((t) => (
                  <tr key={t.id} className="border-t border-slate-100 hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-5">
                      <div className="text-slate-800 text-sm flex items-center gap-1.5">
                        <Calendar className="w-3.5 h-3.5 text-slate-400" />
                        {fmtDateTime(t.start_time)}
                      </div>
                      <p className="text-[11px] text-slate-400 ml-5">→ {fmtDateTime(t.end_time)}</p>
                    </td>
                    <td className="py-3 px-4 text-slate-700">{t.driver_name}</td>
                    <td className="py-3 px-4 text-slate-600 font-mono text-xs">{t.vehicle_plate}</td>
                    {!isMasked && (
                      <td className="py-3 px-4 max-w-md">
                        <div className="text-xs text-slate-600 flex items-start gap-1">
                          <MapPin className="w-3 h-3 mt-0.5 text-[#2196F3] shrink-0" />
                          <span className="truncate">{t.start_address}</span>
                        </div>
                        <div className="text-xs text-slate-500 flex items-start gap-1 mt-0.5">
                          <MapPin className="w-3 h-3 mt-0.5 text-slate-400 shrink-0" />
                          <span className="truncate">{t.end_address}</span>
                        </div>
                      </td>
                    )}
                    <td className="py-3 px-4 text-right font-medium text-slate-800">{fmtKm(t.distance_km)}</td>
                    <td className="py-3 px-4 text-right text-slate-600 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1"><Clock className="w-3 h-3 text-slate-400" />{fmtDuration(t.duration_min)}</span>
                    </td>
                    {!isMasked && (
                      <td className="py-3 px-4 text-right text-slate-600 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1"><Fuel className="w-3 h-3 text-amber-500" />{(t.fuel_l ?? 0).toFixed(2)} L</span>
                      </td>
                    )}
                    {!isMasked && (
                      <td className="py-3 px-4 text-right text-slate-600 whitespace-nowrap">
                        <span className="inline-flex items-center gap-1"><Gauge className="w-3 h-3 text-slate-400" />{(t.max_speed ?? 0).toFixed(0)} km/h</span>
                      </td>
                    )}
                    <td className="py-3 px-4 text-center"><ClassificationBadge value={t.classification} /></td>
                    {canEdit && (
                      <td className="py-3 px-5 text-right">
                        {t.classification === "professional" ? (
                          <Button
                            size="sm" variant="outline"
                            data-testid={TEST_IDS.history.classifyPerso}
                            onClick={() => classify(t, "personal")}
                            className="text-xs h-8"
                          >
                            <ArrowLeftRight className="w-3 h-3 mr-1" /> Personnel
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            data-testid={TEST_IDS.history.classifyPro}
                            onClick={() => classify(t, "professional")}
                            className="text-xs h-8 bg-[#2196F3] hover:bg-[#1E88E5]"
                          >
                            <ArrowLeftRight className="w-3 h-3 mr-1" /> Professionnel
                          </Button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      </>
      )}
    </div>
  );
}
