import { useEffect, useState } from "react";
import { api, downloadBlob } from "@/lib/api";
import { TEST_IDS } from "@/constants/testIds";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { FileText, FileSpreadsheet, FileDown, Briefcase, User } from "lucide-react";

export default function ReportsPage({ kind }) {
  const [filters, setFilters] = useState({ driver_id: "all", vehicle_id: "all", start: "", end: "" });
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      const [d, v] = await Promise.all([
        api.get("/livre/drivers").then(r => r.data),
        api.get("/livre/vehicles").then(r => r.data),
      ]);
      setDrivers(d); setVehicles(v);
    })();
  }, []);

  async function exportReport(fmt) {
    setLoading(true);
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
      const ext = fmt;
      downloadBlob(res.data, `rapport_${kind}_${Date.now()}.${ext}`);
      toast.success(`Export ${fmt.toUpperCase()} prêt`);
    } catch (e) {
      toast.error("Export impossible");
    } finally { setLoading(false); }
  }

  return (
    <div data-testid={TEST_IDS.reports.page} className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Rapports</p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 mt-1 flex items-center gap-3">
          {kind === "pro" ? <Briefcase className="w-6 h-6 text-[#2196F3]" /> : <User className="w-6 h-6 text-slate-500" />}
          {kind === "pro" ? "Rapports professionnels" : "Rapports personnels"}
        </h1>
        <p className="text-sm text-slate-500 mt-1.5">
          Génération de rapports PDF, Excel et CSV à partir des données Navixy.
        </p>
      </div>

      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-6">
        <h3 className="text-sm font-semibold text-slate-800 mb-4">Filtres</h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Chauffeur</p>
            <Select value={filters.driver_id} onValueChange={(v) => setFilters({ ...filters, driver_id: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {drivers.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Véhicule</p>
            <Select value={filters.vehicle_id} onValueChange={(v) => setFilters({ ...filters, vehicle_id: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Du</p>
            <Input type="date" value={filters.start}
              onChange={(e) => setFilters({ ...filters, start: e.target.value })} />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Au</p>
            <Input type="date" value={filters.end}
              onChange={(e) => setFilters({ ...filters, end: e.target.value })} />
          </div>
        </div>

        <div className="mt-6 pt-6 border-t border-slate-100 flex flex-wrap gap-3">
          <Button
            disabled={loading} onClick={() => exportReport("pdf")}
            data-testid={TEST_IDS.reports.btnPdf}
            className="bg-[#2196F3] hover:bg-[#1E88E5] text-white"
          >
            <FileText className="w-4 h-4 mr-2" /> Télécharger PDF
          </Button>
          <Button
            disabled={loading} variant="outline" onClick={() => exportReport("xlsx")}
            data-testid={TEST_IDS.reports.btnXlsx}
          >
            <FileSpreadsheet className="w-4 h-4 mr-2" /> Excel
          </Button>
          <Button
            disabled={loading} variant="outline" onClick={() => exportReport("csv")}
            data-testid={TEST_IDS.reports.btnCsv}
          >
            <FileDown className="w-4 h-4 mr-2" /> CSV
          </Button>
        </div>
      </Card>

      <Card className="bg-blue-50/50 border-blue-200 rounded-md p-5 text-sm text-slate-700">
        <p className="font-medium text-[#1976D2]">À propos des rapports {kind === "pro" ? "professionnels" : "personnels"}</p>
        <p className="text-slate-600 mt-1 leading-relaxed text-xs">
          {kind === "pro"
            ? "Inclut : véhicule, conducteur, départ, arrivée, distance, temps, carburant, vitesses. Distances strictement identiques à celles affichées dans Navixy."
            : "En mode A (visible), le rapport contient les détails complets. En mode B (masqué), seuls la date, la distance et la durée apparaissent — la confidentialité du chauffeur est préservée."}
        </p>
      </Card>
    </div>
  );
}
