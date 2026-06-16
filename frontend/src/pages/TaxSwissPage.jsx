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
import { Receipt, FileText } from "lucide-react";

export default function TaxSwissPage() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [drivers, setDrivers] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [driverId, setDriverId] = useState("all");
  const [vehicleId, setVehicleId] = useState("all");
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

  async function download() {
    setLoading(true);
    try {
      const params = { year };
      if (driverId && driverId !== "all") params.driver_id = driverId;
      if (vehicleId && vehicleId !== "all") params.vehicle_id = vehicleId;
      const res = await api.get("/livre/reports/tax-swiss", { params, responseType: "blob" });
      downloadBlob(res.data, `rapport_fiscal_suisse_${year}.pdf`);
      toast.success("Rapport fiscal généré");
    } catch (e) { toast.error("Génération impossible"); }
    finally { setLoading(false); }
  }

  return (
    <div data-testid={TEST_IDS.reports.page} className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400">Rapport annuel</p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 mt-1 flex items-center gap-3">
          <Receipt className="w-6 h-6 text-[#2196F3]" />
          Rapport fiscal suisse
        </h1>
        <p className="text-sm text-slate-500 mt-1.5 max-w-2xl">
          Document officiel annuel : kilomètres professionnels et personnels, pourcentages privé/pro, carburant.
          Conforme aux exigences fiscales suisses (déduction privé/pro des véhicules d'entreprise).
        </p>
      </div>

      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-6 max-w-3xl">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Année fiscale</p>
            <Input
              type="number" min="2020" max="2099"
              data-testid={TEST_IDS.reports.yearInput}
              value={year}
              onChange={(e) => setYear(parseInt(e.target.value, 10) || year)}
            />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Chauffeur (optionnel)</p>
            <Select value={driverId} onValueChange={setDriverId}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {drivers.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Véhicule (optionnel)</p>
            <Select value={vehicleId} onValueChange={setVehicleId}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous</SelectItem>
                {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="mt-6 pt-6 border-t border-slate-100">
          <Button
            disabled={loading} onClick={download}
            data-testid={TEST_IDS.reports.btnTaxPdf}
            className="bg-[#2196F3] hover:bg-[#1E88E5] text-white"
          >
            <FileText className="w-4 h-4 mr-2" />
            Télécharger le rapport fiscal {year}
          </Button>
        </div>
      </Card>
    </div>
  );
}
