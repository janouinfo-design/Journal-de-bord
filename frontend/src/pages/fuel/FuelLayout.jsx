import { Outlet } from "react-router-dom";
import SubTabs from "@/components/layout/SubTabs";
import { useAuth } from "@/contexts/AuthContext";
import { Gauge, ReceiptText, CreditCard, GitMerge, Upload, Settings2, ListChecks, FileCheck2, AlertTriangle } from "lucide-react";

export default function FuelLayout() {
  const { user } = useAuth();
  const role = user?.role;
  const isAdmin = role === "admin" || role === "superadmin";

  let tabs;
  if (role === "driver") {
    tabs = [
      { to: "/livre/carburant/mes-transactions", label: "Mes transactions", icon: ListChecks, testId: "subtab-fuel-my-transactions" },
    ];
  } else {
    tabs = [
      { to: "/livre/carburant/apercu", label: "Vue d'ensemble", icon: Gauge, testId: "subtab-fuel-overview" },
      { to: "/livre/carburant/transactions", label: "Transactions", icon: ReceiptText, testId: "subtab-fuel-transactions" },
      { to: "/livre/carburant/cartes", label: "Cartes carburant", icon: CreditCard, testId: "subtab-fuel-cards" },
      ...(role === "manager" || isAdmin
        ? [{ to: "/livre/carburant/rapprochements", label: "Rapprochements", icon: GitMerge, testId: "subtab-fuel-matching" }] : []),
      { to: "/livre/carburant/anomalies", label: "Anomalies", icon: AlertTriangle, testId: "subtab-fuel-anomalies" },
      { to: "/livre/carburant/decomptes", label: "Décomptes", icon: FileCheck2, testId: "subtab-fuel-statements" },
      ...(isAdmin ? [{ to: "/livre/carburant/importations", label: "Importations", icon: Upload, testId: "subtab-fuel-imports" }] : []),
      ...(isAdmin ? [{ to: "/livre/carburant/parametres", label: "Paramètres", icon: Settings2, testId: "subtab-fuel-settings" }] : []),
    ];
  }

  return (
    <div data-testid="fuel-page" className="space-y-5">
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400 font-semibold">Carburant & Décomptes</p>
        <h1 className="text-2xl font-semibold text-slate-900">
          {role === "driver" ? "Mes transactions carburant" : "Carburant"}
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          {role === "driver"
            ? "Vos pleins et recharges — consultez le détail, joignez un justificatif ou signalez une erreur."
            : "Cartes carburant, transactions, rapprochement automatique aux véhicules et trajets."}
        </p>
      </div>
      <SubTabs tabs={tabs} />
      <Outlet />
    </div>
  );
}
