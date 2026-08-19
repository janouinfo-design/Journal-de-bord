import { Zap, Fuel, BatteryCharging, Loader2 } from "lucide-react";
import { EnergyBadge } from "./EnergyBadge";

export const POWERTRAIN_LABEL = {
  ICE: "Thermique", HEV: "Hybride", PHEV: "Hybride rechargeable",
  BEV: "Électrique", UNKNOWN: "Motorisation inconnue",
};

const SOURCE_LABEL = {
  OBD: "OBD", CAN: "CAN", NAVIXY_SENSOR: "Capteur Navixy",
  FUEL_TRANSACTION: "Transaction carburant", VEHICLE_SPEC: "Caractéristiques véhicule",
  ENERGY_MODEL: "Modèle Énergie",
};

export const REASON_LABEL = {
  energy_not_connected: "Module Énergie non connecté",
  energy_unreachable: "Module Énergie injoignable",
  no_data: "Aucune donnée transmise par le module Énergie",
  trip_not_found: "Trajet inaccessible",
};

function fmtVal(m, digits) {
  if (!m || m.value == null) return null;
  return `${Number(m.value).toFixed(digits)} ${m.unit || ""}`.trim();
}

function MetricRow({ label, metric, digits = 1, optional = false, testId }) {
  const missing = !metric || metric.availability === "UNAVAILABLE" || metric.value == null;
  if (missing && optional) return null; /* SoC absent → masqué */
  return (
    <div className="flex items-center justify-between gap-3 text-xs" data-testid={testId}>
      <span className="text-slate-500">{label}</span>
      <span className="flex items-center gap-2">
        {missing ? (
          <span className="text-slate-400 italic">Non disponible</span>
        ) : (
          <>
            <span className="font-medium text-slate-800 font-mono">{fmtVal(metric, digits)}</span>
            <EnergyBadge metric={metric} />
            {metric.source && (
              <span className="text-[10px] text-slate-400">· {SOURCE_LABEL[metric.source] || metric.source}</span>
            )}
          </>
        )}
      </span>
    </div>
  );
}

export function TripEnergyBlock({ data, loading }) {
  if (loading && !data) {
    return (
      <p className="text-xs text-slate-400 py-1.5 flex items-center gap-1.5">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Chargement énergie…
      </p>
    );
  }
  if (!data) return null;

  if (data.availability === "UNAVAILABLE") {
    return (
      <div className="rounded-md border border-slate-200 bg-slate-50/60 px-4 py-2.5" data-testid="trip-energy-unavailable">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
          <Zap className="w-3 h-3" /> Énergie
        </p>
        <div className="text-xs text-slate-500 mt-1 flex items-center gap-2 flex-wrap">
          <EnergyBadge kind="unavailable" />
          {REASON_LABEL[data.reason] || "Non disponible"}
          {data.mode === "fixture" && (
            <span className="text-[9px] uppercase tracking-wider text-violet-600 border border-violet-200 bg-violet-50 rounded px-1.5 py-0.5"
                  data-testid="trip-energy-fixture-flag">
              Fixture — démo contractuelle
            </span>
          )}
        </div>
      </div>
    );
  }

  const stale = data.availability === "STALE";
  const el = data.electric || {};
  const fu = data.fuel || {};
  const hasElectric = data.electric != null;
  const hasFuel = data.fuel != null;

  return (
    <div className="rounded-md border border-slate-200 bg-white px-4 py-3 space-y-2" data-testid="trip-energy-block">
      <div className="flex items-center gap-2 flex-wrap">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
          <Zap className="w-3 h-3" /> Énergie
        </p>
        {data.powertrain && (
          <span className="text-[10px] text-slate-500 border border-slate-200 rounded px-1.5 py-0.5"
                data-testid="trip-energy-powertrain">
            {POWERTRAIN_LABEL[data.powertrain] || data.powertrain}
          </span>
        )}
        {stale && <EnergyBadge kind="stale" testId="trip-energy-stale" />}
        {data.mode === "fixture" && (
          <span className="text-[9px] uppercase tracking-wider text-violet-600 border border-violet-200 bg-violet-50 rounded px-1.5 py-0.5"
                data-testid="trip-energy-fixture-flag">
            Fixture — démo contractuelle
          </span>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1.5 max-w-2xl">
        {hasElectric && (
          <div className="space-y-1.5">
            <p className="text-[10px] text-slate-400 flex items-center gap-1">
              <BatteryCharging className="w-3 h-3" /> Électrique
            </p>
            <MetricRow label="SoC départ" metric={el.soc_start_pct} digits={0} optional testId="energy-soc-start" />
            <MetricRow label="SoC arrivée" metric={el.soc_end_pct} digits={0} optional testId="energy-soc-end" />
            <MetricRow label="Énergie" metric={el.energy_kwh} testId="energy-kwh" />
            <MetricRow label="Consommation" metric={el.consumption_kwh_100km} testId="energy-kwh-100" />
          </div>
        )}
        {hasFuel && (
          <div className="space-y-1.5">
            <p className="text-[10px] text-slate-400 flex items-center gap-1">
              <Fuel className="w-3 h-3" /> Carburant
            </p>
            <MetricRow label="Carburant utilisé" metric={fu.fuel_liters} testId="energy-fuel-l" />
            <MetricRow label="Consommation" metric={fu.consumption_l_100km} testId="energy-l-100" />
          </div>
        )}
        {!hasElectric && !hasFuel && (
          <p className="text-xs text-slate-400 italic">Non disponible</p>
        )}
      </div>
    </div>
  );
}
