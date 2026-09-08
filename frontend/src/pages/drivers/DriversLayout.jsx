import { Outlet } from "react-router-dom";
import SubTabs from "@/components/layout/SubTabs";
import { Gauge, IdCard, Bluetooth, History, Leaf } from "lucide-react";

export default function DriversLayout() {
  const tabs = [
    { to: "/livre/conducteurs/vue-densemble", label: "Vue d'ensemble", icon: Gauge, testId: "subtab-drivers-overview" },
    { to: "/livre/conducteurs/chauffeurs", label: "Chauffeurs", icon: IdCard, testId: "subtab-drivers-list" },
    { to: "/livre/conducteurs/identification", label: "Identification", icon: Bluetooth, testId: "subtab-drivers-identification" },
    { to: "/livre/conducteurs/sessions", label: "Sessions", icon: History, testId: "subtab-drivers-sessions" },
    { to: "/livre/conducteurs/eco-conduite", label: "Éco-conduite", icon: Leaf, testId: "subtab-drivers-eco" },
  ];
  return (
    <div data-testid="drivers-domain-page" className="space-y-5">
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400 font-semibold">Conducteurs</p>
        <h1 className="text-2xl font-semibold text-slate-900">Conducteurs</h1>
        <p className="text-sm text-slate-500 mt-1">
          Chauffeurs, identification APP/BLE, sessions de conduite et éco-conduite.
        </p>
      </div>
      <SubTabs tabs={tabs} />
      <Outlet />
    </div>
  );
}
