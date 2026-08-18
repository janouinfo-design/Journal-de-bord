/* Widget Carburant du tableau de bord principal — chiffres 100 % backend
 * (tenant + RBAC serveur), chaque indicateur ouvre la liste déjà filtrée. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtAmount } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { STATEMENT_STATUS } from "@/lib/fuelLabels";
import {
  Fuel, ChevronRight, TrendingUp, TrendingDown, Droplets, Zap,
  GitMerge, Landmark, AlertTriangle, FileCheck2,
} from "lucide-react";

const MONTH_LABELS = ["janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

function monthLabel(ym) {
  if (!ym) return "";
  const [y, m] = ym.split("-");
  return `${MONTH_LABELS[Number(m) - 1]} ${y}`;
}

function Metric({ to, label, value, sub, icon: Icon, tone = "text-slate-900", testId }) {
  return (
    <Link to={to} data-testid={testId}
          className="rounded-md border border-transparent hover:border-sky-200 hover:bg-white/70 p-2 transition-colors block">
      <p className="text-[10px] text-slate-500 flex items-center gap-1">
        {Icon && <Icon className="w-3 h-3" />} {label}
      </p>
      <p className={`text-lg font-semibold leading-tight ${tone}`}>{value}</p>
      {sub && <p className="text-[10px] text-slate-400">{sub}</p>}
    </Link>
  );
}

export default function FuelWidget() {
  const [d, setD] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.get("/livre/fuel/widget")
      .then((r) => { if (!cancelled) setD(r.data); })
      .catch(() => { /* chauffeur : 403 — widget masqué */ });
    return () => { cancelled = true; };
  }, []);

  if (!d) return null;
  const txLink = `/livre/carburant/transactions?date_from=${d.date_from}&date_to=${d.date_to}`;
  const st = d.statement.exists ? STATEMENT_STATUS[d.statement.status] : null;

  return (
    <Card data-testid="dashboard-fuel-widget"
          className="p-4 bg-gradient-to-br from-sky-50 to-emerald-50 border-sky-100">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-white border border-sky-200">
            <Fuel className="w-4 h-4 text-sky-600" />
          </div>
          <span className="text-[10px] uppercase tracking-[0.14em] text-sky-700 font-semibold">
            Carburant — {monthLabel(d.month)}
          </span>
        </div>
        <Link to="/livre/carburant/apercu" data-testid="dashboard-fuel-widget-open"
              className="text-sky-500 hover:translate-x-1 transition-transform">
          <ChevronRight className="w-4 h-4" />
        </Link>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-1.5">
        <Metric to={txLink} label="Coût du mois (CHF)" value={fmtAmount(d.current.amount_chf)}
                testId="fuel-widget-amount"
                sub={d.delta_pct != null
                  ? `${d.delta_pct > 0 ? "+" : ""}${d.delta_pct} % vs ${monthLabel(d.previous.month)}`
                  : `${monthLabel(d.previous.month)} : ${d.previous.tx_count ? fmtAmount(d.previous.amount_chf) : "aucune donnée"}`}
                icon={d.delta_pct != null && d.delta_pct > 0 ? TrendingUp
                  : d.delta_pct != null ? TrendingDown : undefined}
                tone={d.delta_pct != null && d.delta_pct > 0 ? "text-rose-600" : "text-slate-900"} />
        <Metric to={txLink} label="Litres" value={`${d.current.liters} L`}
                sub={`${d.current.tx_count} transaction(s)`} icon={Droplets} testId="fuel-widget-liters" />
        <Metric to={txLink} label="Recharge" value={`${d.current.kwh} kWh`} icon={Zap}
                testId="fuel-widget-kwh" />
        <Metric to="/livre/carburant/transactions?match_status=unmatched" label="Non rapprochées"
                value={d.unmatched_count} icon={GitMerge}
                tone={d.unmatched_count ? "text-amber-600" : "text-emerald-600"}
                testId="fuel-widget-unmatched" />
        <Metric to="/livre/carburant/transactions?fx_status=pending" label="Conversions en attente"
                value={d.fx_pending_count} icon={Landmark}
                tone={d.fx_pending_count ? "text-amber-600" : "text-emerald-600"}
                testId="fuel-widget-fx" />
        <Metric to="/livre/carburant/anomalies" label="Anomalies ouvertes"
                value={d.anomalies.open} icon={AlertTriangle}
                sub={d.anomalies.critical ? `dont ${d.anomalies.critical} critique(s)` : null}
                tone={d.anomalies.critical ? "text-rose-600" : d.anomalies.open ? "text-amber-600" : "text-emerald-600"}
                testId="fuel-widget-anomalies" />
        <Metric to={d.statement.exists ? `/livre/carburant/decomptes/${d.statement.id}` : "/livre/carburant/decomptes"}
                label={`Décompte ${monthLabel(d.statement.period_month)}`}
                value={st ? st.label : "À créer"} icon={FileCheck2}
                sub={d.statement.exists ? d.statement.number : "Aucun décompte généré"}
                tone={st ? (d.statement.status === "closed" ? "text-emerald-600" : "text-amber-600") : "text-slate-500"}
                testId="fuel-widget-statement" />
      </div>
    </Card>
  );
}
