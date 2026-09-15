import { useEffect, useState } from "react";
import { api, fmtKm, fmtDateTime } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { TripEnergyBlock } from "@/components/energy/TripEnergyBlock";
import { AlertTriangle, Loader2 } from "lucide-react";

const MAX_TRIPS = 30;

export default function EnergyConsumptionPage() {
  const [status, setStatus] = useState(null);
  const [vehicles, setVehicles] = useState([]);
  const [trips, setTrips] = useState([]);
  const [energyById, setEnergyById] = useState({});
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ vehicle_id: "all", start: "", end: "" });

  useEffect(() => {
    api.get("/livre/energy/status").then(r => setStatus(r.data)).catch(() => {});
    api.get("/livre/vehicles").then(r => setVehicles(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const params = { limit: MAX_TRIPS };
        if (filters.vehicle_id !== "all") params.vehicle_id = filters.vehicle_id;
        if (filters.start) params.start = new Date(filters.start).toISOString();
        if (filters.end) params.end = new Date(filters.end).toISOString();
        const { data } = await api.get("/livre/trips", { params });
        const rows = (data.trips || [])
          .slice()
          .sort((a, b) => (b.start_time || "").localeCompare(a.start_time || ""))
          .slice(0, MAX_TRIPS);
        setTrips(rows);
        if (rows.length) {
          const { data: e } = await api.post("/livre/energy/trips",
            { trip_ids: rows.map(t => t.id) });
          const map = {};
          (e.results || []).forEach(r => { map[r.trip_id] = r; });
          setEnergyById(map);
        } else {
          setEnergyById({});
        }
      } finally { setLoading(false); }
    })();
  }, [filters]);

  const notConnected = status && !status.connected;

  return (
    <div data-testid="energy-consumption-page" className="space-y-5">
      <p className="text-sm text-slate-500">
        Résumé énergie par trajet, fourni par le module Énergie — le Journal n&apos;effectue aucun calcul.
        Affichage des {MAX_TRIPS} trajets les plus récents selon les filtres.
      </p>

      {notConnected && (
        <div data-testid="energy-consumption-banner"
             className="bg-amber-50 border border-amber-200 text-amber-800 rounded-md px-4 py-3 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Module Énergie non connecté — les consommations ci-dessous sont « Non disponible » tant que la dépendance n&apos;est pas branchée.
        </div>
      )}

      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Véhicule</p>
            <Select value={filters.vehicle_id} onValueChange={(v) => setFilters({ ...filters, vehicle_id: v })}>
              <SelectTrigger data-testid="energy-filter-vehicle"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tous les véhicules</SelectItem>
                {vehicles.map(v => <SelectItem key={v.id} value={v.id}>{v.plate} — {v.model}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Du</p>
            <Input type="date" data-testid="energy-filter-start"
                   value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value })} />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Au</p>
            <Input type="date" data-testid="energy-filter-end"
                   value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value })} />
          </div>
        </div>
      </Card>

      <Card className="bg-white border-slate-200 shadow-sm rounded-md overflow-hidden">
        {loading ? (
          <div className="py-16 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>
        ) : trips.length === 0 ? (
          <div className="py-16 text-center text-slate-500 text-sm">Aucun trajet sur cette période.</div>
        ) : (
          <div className="divide-y divide-slate-100" data-testid="energy-consumption-list">
            {trips.map(t => (
              <div key={t.id} className="px-5 py-3 grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-3 items-start"
                   data-testid={`energy-trip-row-${t.id}`}>
                <div className="text-xs space-y-0.5">
                  <p className="text-slate-800 font-medium">{fmtDateTime(t.start_time)}</p>
                  <p className="text-slate-500 font-mono">{t.vehicle_plate}</p>
                  <p className="text-slate-500">{t.driver_name}</p>
                  <p className="text-slate-600 font-medium">{fmtKm(t.distance_km)}</p>
                </div>
                <TripEnergyBlock data={energyById[t.id]} loading={!energyById[t.id]} />
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
