import { useEffect, useMemo, useState } from "react";
import { api, fmtKm, fmtPct, fmtDuration } from "@/lib/api";
import { KpiCard } from "@/components/livre/KpiCard";
import { TEST_IDS } from "@/constants/testIds";
import { ProBadge, PersoBadge } from "@/components/livre/Badges";
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Legend,
} from "recharts";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Briefcase, User, Activity, PieChart as PieIcon, Fuel, Gauge, Loader2, AlertCircle, Filter,
} from "lucide-react";

const COLORS = ["#2196F3", "#94A3B8"];

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [groups, setGroups] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [filters, setFilters] = useState({
    driver_id: "all", vehicle_id: "all", group: "all", company: "all", start: "", end: "",
  });

  useEffect(() => {
    (async () => {
      const [d, v, g, c] = await Promise.all([
        api.get("/livre/drivers").then(r => r.data),
        api.get("/livre/vehicles").then(r => r.data),
        api.get("/livre/groups").then(r => r.data).catch(() => []),
        api.get("/livre/companies").then(r => r.data).catch(() => []),
      ]);
      setDrivers(d); setVehicles(v); setGroups(g); setCompanies(c);
    })();
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const params = {};
        if (filters.driver_id !== "all") params.driver_id = filters.driver_id;
        if (filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
        if (filters.group !== "all") params.group = filters.group;
        if (filters.company !== "all") params.company = filters.company;
        if (filters.start) params.start = new Date(filters.start).toISOString();
        if (filters.end) params.end = new Date(filters.end).toISOString();
        const { data } = await api.get("/livre/dashboard", { params });
        setData(data);
      } finally { setLoading(false); }
    })();
  }, [filters]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" />
      </div>
    );
  }
  if (!data) return null;

  const k = data.kpi;
  const pieData = [
    { name: "Professionnel", value: k.pro_km },
    { name: "Personnel", value: k.perso_km },
  ];

  return (
    <div data-testid={TEST_IDS.dashboard.page} className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Tableau de bord</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900 mt-1">Livre de Bord</h1>
          <p className="text-sm text-slate-500 mt-1.5">
            Vue d&apos;ensemble des kilomètres professionnels et personnels — données GPS officielles LOGITRAK.
          </p>
        </div>
        <div className="text-right">
          <p className="text-[11px] uppercase tracking-[0.15em] text-slate-400">Politique</p>
          <p className="text-sm font-medium text-slate-700 mt-0.5">
            {data.settings_mode === "mixte" && "Mode Mixte"}
            {data.settings_mode === "masked" && "Personnel Masqué"}
            <span className="text-slate-400 font-normal">
              {data.settings_mode === "mixte" && " — Pro et perso visibles"}
              {data.settings_mode === "masked" && " — Trajets privés anonymisés"}
            </span>
          </p>
        </div>
      </div>

      <Card data-testid="dashboard-filters" className="bg-white border-slate-200 shadow-sm rounded-md p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-slate-500" />
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-600">Filtres</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Chauffeur</p>
            <Select value={filters.driver_id} onValueChange={(v) => setFilters({ ...filters, driver_id: v })}>
              <SelectTrigger data-testid={TEST_IDS.dashboard.filterDriver}><SelectValue placeholder="Tous" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {drivers.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Véhicule</p>
            <Select value={filters.vehicle_id} onValueChange={(v) => setFilters({ ...filters, vehicle_id: v })}>
              <SelectTrigger data-testid={TEST_IDS.dashboard.filterVehicle}><SelectValue placeholder="Tous" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Groupe</p>
            <Select value={filters.group} onValueChange={(v) => setFilters({ ...filters, group: v })}>
              <SelectTrigger data-testid={TEST_IDS.dashboard.filterGroup}><SelectValue placeholder="Tous" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {groups.map(g => <SelectItem key={g.id} value={g.id}>{g.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Société</p>
            <Select value={filters.company} onValueChange={(v) => setFilters({ ...filters, company: v })}>
              <SelectTrigger data-testid={TEST_IDS.dashboard.filterCompany}><SelectValue placeholder="Toutes" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Toutes</SelectItem>
                {companies.map(c => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Du</p>
            <Input type="date" data-testid={TEST_IDS.dashboard.filterStart}
              value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value })} />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Au</p>
            <Input type="date" data-testid={TEST_IDS.dashboard.filterEnd}
              value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value })} />
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard testId={TEST_IDS.dashboard.kpiProKm} label="Km professionnels" value={fmtKm(k.pro_km)} accent="pro" icon={Briefcase}
          sub={`${k.trips_count} trajets · ${fmtDuration(k.pro_time_min)}`} />
        <KpiCard testId={TEST_IDS.dashboard.kpiPersoKm} label="Km personnels" value={fmtKm(k.perso_km)} accent="perso" icon={User}
          sub={`${fmtDuration(k.perso_time_min)} de conduite`} />
        <KpiCard testId={TEST_IDS.dashboard.kpiTotalKm} label="Km totaux" value={fmtKm(k.total_km)} icon={Activity}
          sub="Toutes catégories" />
        <KpiCard testId={TEST_IDS.dashboard.kpiUnclassifiedKm} label="Km non classifiés" value={fmtKm(k.unclassified_km || 0)}
          accent={(k.unclassified_km || 0) > 0 ? "warning" : "default"} icon={AlertCircle}
          sub={(k.unclassified_km || 0) > 0 ? "Trajets sans règle correspondante" : "Tout classé"} />
        <KpiCard testId={TEST_IDS.dashboard.kpiPctPro} label="% professionnel" value={fmtPct(k.pct_pro)} accent="pro" icon={PieIcon} />
        <KpiCard testId={TEST_IDS.dashboard.kpiPctPerso} label="% personnel" value={fmtPct(k.pct_perso)} accent="perso" icon={PieIcon} />
        <KpiCard testId={TEST_IDS.dashboard.kpiFuel} label="Carburant professionnel" value={`${k.pro_fuel.toFixed(1)} L`} accent="pro" icon={Fuel}
          sub="Consommation pro" />
        <KpiCard testId={TEST_IDS.dashboard.kpiFuelPerso} label="Carburant personnel" value={`${k.perso_fuel.toFixed(1)} L`} accent="warning" icon={Fuel}
          sub="Consommation perso" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card data-testid={TEST_IDS.dashboard.pieChart} className="bg-white border-slate-200 shadow-sm p-5 rounded-md">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-slate-800">Répartition pro / perso</h3>
            <Gauge className="w-4 h-4 text-slate-400" />
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={90} paddingAngle={2} dataKey="value">
                {pieData.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
              </Pie>
              <Tooltip formatter={(v) => fmtKm(v)} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex justify-around text-center text-xs text-slate-600 mt-2">
            <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-sm bg-[#2196F3]" /> Pro {fmtPct(k.pct_pro)}</div>
            <div className="flex items-center gap-2"><span className="w-3 h-3 rounded-sm bg-slate-400" /> Perso {fmtPct(k.pct_perso)}</div>
          </div>
        </Card>

        <Card data-testid={TEST_IDS.dashboard.lineChart} className="bg-white border-slate-200 shadow-sm p-5 rounded-md lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-slate-800">Évolution sur 30 jours</h3>
            <span className="text-xs text-slate-400">km/jour</span>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={data.daily_series} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#F1F5F9" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="#94A3B8" fontSize={10} tickFormatter={(d) => d.slice(5)} />
              <YAxis stroke="#94A3B8" fontSize={10} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="pro" name="Pro" stroke="#2196F3" strokeWidth={2.5} dot={false} />
              <Line type="monotone" dataKey="perso" name="Perso" stroke="#94A3B8" strokeWidth={2.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card className="bg-white border-slate-200 shadow-sm rounded-md overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">Synthèse par chauffeur</h3>
            <p className="text-xs text-slate-500 mt-0.5">Période : 45 derniers jours</p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table data-testid={TEST_IDS.dashboard.table} className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 text-slate-500 text-xs font-medium uppercase tracking-wider">
                <th className="text-left py-3 px-5">Chauffeur</th>
                <th className="text-left py-3 px-4">Véhicule</th>
                <th className="text-right py-3 px-4">Km pro</th>
                <th className="text-right py-3 px-4">Km perso</th>
                <th className="text-right py-3 px-4">Km totaux</th>
                <th className="text-right py-3 px-4">Temps pro</th>
                <th className="text-right py-3 px-4">Temps perso</th>
                <th className="text-right py-3 px-5">% pro / perso</th>
              </tr>
            </thead>
            <tbody>
              {data.table.map((r) => (
                <tr key={r.driver_id} className="border-t border-slate-100 hover:bg-slate-50 transition-colors">
                  <td className="py-3 px-5 font-medium text-slate-800">{r.driver_name}</td>
                  <td className="py-3 px-4 text-slate-600 font-mono text-xs">{r.vehicle_plate}</td>
                  <td className="py-3 px-4 text-right text-[#1976D2] font-medium">{fmtKm(r.pro_km)}</td>
                  <td className="py-3 px-4 text-right text-slate-600">{fmtKm(r.perso_km)}</td>
                  <td className="py-3 px-4 text-right font-semibold text-slate-900">{fmtKm(r.total_km)}</td>
                  <td className="py-3 px-4 text-right text-slate-600">{fmtDuration(r.pro_time)}</td>
                  <td className="py-3 px-4 text-right text-slate-500">{fmtDuration(r.perso_time)}</td>
                  <td className="py-3 px-5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <ProBadge /><span className="text-xs text-slate-500">{r.pct_pro}%</span>
                      <PersoBadge /><span className="text-xs text-slate-500">{r.pct_perso}%</span>
                    </div>
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
