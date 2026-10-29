import { Outlet } from "react-router-dom";
import SubTabs from "@/components/layout/SubTabs";
import { useAuth } from "@/contexts/AuthContext";
import { Gauge, IdCard, Bluetooth, History, Leaf } from "lucide-react";

export default function DriversLayout() {
  const { can } = useAuth();
  const tabs = [
    { to: "/livre/conducteurs/vue-densemble", label: "Vue d'ensemble", icon: Gauge, testId: "subtab-drivers-overview", perms: ["drivers.view"] },
    { to: "/livre/conducteurs/chauffeurs", label: "Chauffeurs", icon: IdCard, testId: "subtab-drivers-list", perms: ["drivers.view"] },
    { to: "/livre/conducteurs/identification", label: "Identification", icon: Bluetooth, testId: "subtab-drivers-identification", perms: ["identification.view"] },
    { to: "/livre/conducteurs/sessions", label: "Sessions", icon: History, testId: "subtab-drivers-sessions", perms: ["identification.view"] },
    { to: "/livre/conducteurs/eco-conduite", label: "Éco-conduite", icon: Leaf, testId: "subtab-drivers-eco", perms: ["drivers.view"] },
  ].filter((t) => can(...t.perms));
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
