import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { EnergyBadge } from "@/components/energy/EnergyBadge";
import {
  Zap, Fuel, PlugZap, Gauge, Car, AlertTriangle, ArrowRight, Loader2,
} from "lucide-react";

const ENERGY_KPIS = [
  { key: "thermal_consumption_l_100km", label: "Consommation thermique", icon: Fuel },
  { key: "electric_consumption_kwh_100km", label: "Consommation électrique", icon: PlugZap },
  { key: "fuel_liters_total", label: "Litres consommés", icon: Fuel },
  { key: "electric_kwh_total", label: "kWh consommés", icon: Zap },
  { key: "obd_coverage_pct", label: "Couverture OBD", icon: Gauge },
  { key: "vehicles_with_data", label: "Véhicules avec données", icon: Car },
];

function MetricCard({ label, icon: Icon, metric, testId }) {
  const missing = !metric || metric.availability === "UNAVAILABLE" || metric.value == null;
  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid={testId}>
      <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
        <Icon className="w-3 h-3" /> {label}
      </p>
      {missing ? (
        <div className="mt-1.5 flex items-center gap-2">
          <p className="text-sm text-slate-400 italic">Non disponible</p>
          <EnergyBadge kind="unavailable" />
        </div>
      ) : (
        <div className="mt-1.5 flex items-center gap-2 flex-wrap">
          <p className="text-xl font-semibold text-slate-800">
            {Number(metric.value).toLocaleString("fr-CH")} <span className="text-xs text-slate-500 font-normal">{metric.unit === "count" ? "" : metric.unit}</span>
          </p>
          <EnergyBadge metric={metric} />
        </div>
      )}
    </Card>
  );
}

export default function EnergyOverviewPage() {
  const [status, setStatus] = useState(null);
  const [overview, setOverview] = useState(null);
  const [widget, setWidget] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [s, o, w] = await Promise.allSettled([
        api.get("/livre/energy/status").then(r => r.data),
        api.get("/livre/energy/overview").then(r => r.data),
        api.get("/livre/fuel/widget").then(r => r.data),
      ]);
      if (s.status === "fulfilled") setStatus(s.value);
      if (o.status === "fulfilled") setOverview(o.value);
      if (w.status === "fulfilled") setWidget(w.value);
      setLoading(false);
    })();
  }, []);

  if (loading) {
    return <div className="py-16 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>;
  }

  const connected = status?.connected;
  const fixture = status?.mode === "fixture";
  const metrics = overview?.energy?.metrics || null;
  const fleet = overview?.fleet || {};

  return (
    <div data-testid="energy-overview-page" className="space-y-6">
      {/* État de la connexion au module Énergie */}
      {fixture ? (
        <div data-testid="energy-status-banner"
             className="bg-violet-50 border border-violet-200 text-violet-800 rounded-md px-4 py-3 text-sm flex items-center gap-2">
          <Zap className="w-4 h-4 shrink-0" />
          Mode FIXTURE actif — données de démonstration contractuelles, PAS le module Énergie réel.
        </div>
      ) : !connected ? (
        <div data-testid="energy-status-banner"
             className="bg-amber-50 border border-amber-200 text-amber-800 rounded-md px-4 py-3 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>
            <strong>Module Énergie non connecté</strong> — dépendance externe. Les consommations réelles
            (L/100 km, kWh/100 km, SoC) apparaîtront dès que <code className="font-mono text-xs">ENERGY_API_BASE_URL</code> sera configurée.
            Aucune valeur n&apos;est calculée ni inventée par le Journal.
          </span>
        </div>
      ) : (
        <div data-testid="energy-status-banner"
             className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-md px-4 py-3 text-sm flex items-center gap-2">
          <Zap className="w-4 h-4 shrink-0" /> Module Énergie connecté (contrat {String(status?.contract_version || "1.0").startsWith("v") ? status.contract_version : `v${status?.contract_version || "1.0"}`}).
        </div>
      )}

      {/* Consommations — module Énergie uniquement */}
      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
            <Zap className="w-4 h-4 text-[#2196F3]" /> Consommations (module Énergie)
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Mois en cours ({overview?.period?.from} → {overview?.period?.to}) — uniquement les indicateurs réellement fournis.
          </p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          {ENERGY_KPIS.map(k => (
            <MetricCard key={k.key} label={k.label} icon={k.icon}
                        metric={metrics ? metrics[k.key] : null}
                        testId={`energy-kpi-${k.key}`} />
          ))}
        </div>
      </section>

      {/* Flotte — comptages honnêtes du Journal */}
      <section className="space-y-3">
        <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
          <Car className="w-4 h-4 text-slate-500" /> Flotte
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-fleet-total">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Véhicules</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">{fleet.vehicles_total ?? "—"}</p>
          </Card>
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-fleet-powertrain">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Motorisation renseignée</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">
              {fleet.powertrain_set ?? 0}<span className="text-sm text-slate-400 font-normal"> / {fleet.vehicles_total ?? 0}</span>
            </p>
            <p className="text-[10px] text-slate-400 mt-1">Proviendra des capabilities du module Énergie</p>
          </Card>
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-fleet-tank">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Capacité réservoir (réf.)</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">
              {fleet.tank_capacity_set ?? 0}<span className="text-sm text-slate-400 font-normal"> / {fleet.vehicles_total ?? 0}</span>
            </p>
          </Card>
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-fleet-battery">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Capacité batterie (réf.)</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">
              {fleet.battery_capacity_set ?? 0}<span className="text-sm text-slate-400 font-normal"> / {fleet.vehicles_total ?? 0}</span>
            </p>
          </Card>
        </div>
      </section>

      {/* Approvisionnements — achats, concept DISTINCT de la consommation réelle */}
      <section className="space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
              <Fuel className="w-4 h-4 text-amber-500" /> Approvisionnements (achats)
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Transactions cartes carburant : litres/kWh achetés et montants facturés — pas la consommation réelle des véhicules.
            </p>
          </div>
          <Link to="/livre/energie/approvisionnements" data-testid="energy-supply-link"
                className="text-xs text-[#2196F3] hover:underline flex items-center gap-1">
            Ouvrir les approvisionnements <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-supply-cost">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Coût du mois</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">
              {widget ? `${widget.current.amount_chf.toLocaleString("fr-CH")} CHF` : "—"}
            </p>
          </Card>
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-supply-liters">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Litres achetés</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">{widget ? `${widget.current.liters} L` : "—"}</p>
          </Card>
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-supply-kwh">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Recharges achetées</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">{widget ? `${widget.current.kwh} kWh` : "—"}</p>
          </Card>
          <Card className="bg-white border-slate-200 shadow-sm rounded-md p-4" data-testid="energy-supply-tx">
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Transactions</p>
            <p className="text-xl font-semibold text-slate-800 mt-1">{widget ? widget.current.tx_count : "—"}</p>
          </Card>
        </div>
      </section>
    </div>
  );
}
