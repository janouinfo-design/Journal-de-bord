import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import {
  Users, Smartphone, History, AlertTriangle, XCircle, CheckCircle2, Loader2,
} from "lucide-react";

function Stat({ label, value, sub, icon: Icon, to, cls = "text-slate-800", testId }) {
  const body = (
    <Card className={`bg-white border-slate-200 shadow-sm rounded-md p-4 h-full ${to ? "hover:border-[#2196F3]/50 hover:bg-blue-50/30 transition-colors cursor-pointer" : ""}`}
          data-testid={testId}>
      <p className="text-[10px] uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
        {Icon && <Icon className="w-3 h-3" />} {label}
      </p>
      <p className={`text-xl font-semibold mt-1 ${cls}`}>{value}</p>
      {sub && <p className="text-[11px] text-slate-400 mt-0.5">{sub}</p>}
    </Card>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

export default function DriversOverviewPage() {
  const [drivers, setDrivers] = useState(null);
  const [kpis, setKpis] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [d, k] = await Promise.allSettled([
        api.get("/livre/team/drivers").then(r => r.data),
        api.get("/livre/ble/dashboard").then(r => r.data),
      ]);
      if (d.status === "fulfilled") setDrivers(d.value);
      if (k.status === "fulfilled") setKpis(k.value);
      setLoading(false);
    })();
  }, []);

  if (loading) {
    return <div className="py-16 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" /></div>;
  }

  const total = drivers?.length ?? 0;
  const active = (drivers || []).filter(d => d.active !== false).length;
  const withAccount = (drivers || []).filter(d => d.account?.active).length;
  const inSession = (drivers || []).filter(d => d.current_session).length;

  return (
    <div data-testid="drivers-overview-page" className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Chauffeurs" value={total} sub={`${active} actif${active > 1 ? "s" : ""}`}
              icon={Users} to="/livre/conducteurs/chauffeurs" testId="drivers-kpi-total" />
        <Stat label="Comptes mobiles actifs" value={withAccount} icon={Smartphone}
              to="/livre/conducteurs/chauffeurs" testId="drivers-kpi-accounts" />
        <Stat label="En session" value={inSession} icon={History} cls="text-emerald-600"
              to="/livre/conducteurs/sessions" testId="drivers-kpi-in-session" />
        <Stat label="Sessions (période)" value={kpis?.total_sessions ?? 0} icon={History}
              to="/livre/conducteurs/sessions" testId="drivers-kpi-sessions" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Identifiés APP+BLE" value={kpis?.identified_app_ble ?? 0} icon={CheckCircle2}
              cls="text-emerald-600" to="/livre/conducteurs/identification" testId="drivers-kpi-app-ble" />
        <Stat label="À valider" value={kpis?.pending_validation ?? 0} icon={AlertTriangle}
              cls="text-amber-600" to="/livre/conducteurs/identification" testId="drivers-kpi-pending" />
        <Stat label="Conflits" value={kpis?.conflicts ?? 0} icon={XCircle}
              cls="text-rose-600" to="/livre/conducteurs/identification" testId="drivers-kpi-conflicts" />
        <Stat label="Taux d'identification" value={`${kpis?.success_rate ?? 0}%`} icon={CheckCircle2}
              cls="text-emerald-600" to="/livre/conducteurs/identification" testId="drivers-kpi-rate" />
      </div>
      <p className="text-xs text-slate-400">
        Les indicateurs d&apos;identification proviennent des sessions APP / BLE / APP+BLE / MANUEL de la période courante.
      </p>
    </div>
  );
}
