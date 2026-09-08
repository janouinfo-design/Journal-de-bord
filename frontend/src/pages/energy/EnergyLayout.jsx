import { Outlet } from "react-router-dom";
import SubTabs from "@/components/layout/SubTabs";
import { useAuth } from "@/contexts/AuthContext";
import { Gauge, Zap, Fuel, AlertTriangle, Scale } from "lucide-react";

export default function EnergyLayout() {
  const { user } = useAuth();
  const isDriver = user?.role === "driver";

  const tabs = isDriver ? [] : [
    { to: "/livre/energie/apercu", label: "Vue d'ensemble", icon: Gauge, testId: "subtab-energy-overview" },
    { to: "/livre/energie/consommations", label: "Consommations", icon: Zap, testId: "subtab-energy-consumption" },
    { to: "/livre/energie/approvisionnements", label: "Approvisionnements", icon: Fuel,
      testId: "subtab-energy-supply", matchPrefix: "/livre/energie/approvisionnements" },
    { to: "/livre/energie/rapprochement", label: "Rapprochement", icon: Scale, testId: "subtab-energy-reconciliation" },
    { to: "/livre/energie/anomalies", label: "Anomalies", icon: AlertTriangle, testId: "subtab-energy-anomalies" },
  ];

  return (
    <div data-testid="energy-page" className="space-y-5">
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400 font-semibold">Énergie & carburant</p>
        <h1 className="text-2xl font-semibold text-slate-900">
          {isDriver ? "Mes transactions carburant" : "Énergie & carburant"}
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          {isDriver
            ? "Vos pleins et recharges — consultez le détail, joignez un justificatif ou signalez une erreur."
            : "Consommations réelles (module Énergie) et approvisionnements (cartes carburant) — deux concepts distincts."}
        </p>
      </div>
      {!isDriver && <SubTabs tabs={tabs} />}
      <Outlet />
    </div>
  );
}
