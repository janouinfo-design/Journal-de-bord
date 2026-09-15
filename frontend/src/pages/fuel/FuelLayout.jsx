import { Outlet } from "react-router-dom";
import SubTabs from "@/components/layout/SubTabs";
import { useAuth } from "@/contexts/AuthContext";
import { Gauge, ReceiptText, CreditCard, GitMerge, Upload, Settings2, ListChecks, FileCheck2 } from "lucide-react";

/* Branche « Approvisionnements » du domaine Énergie & carburant.
   Achats carburant/recharge (transactions, cartes, décomptes) — concept
   distinct de la consommation réelle fournie par le module Énergie. */
const BASE = "/livre/energie/approvisionnements";

export default function FuelLayout() {
  const { user } = useAuth();
  const role = user?.role;
  const isAdmin = role === "admin" || role === "superadmin";

  let tabs;
  if (role === "driver") {
    tabs = [
      { to: `${BASE}/mes-transactions`, label: "Mes transactions", icon: ListChecks, testId: "subtab-fuel-my-transactions" },
    ];
  } else {
    tabs = [
      { to: `${BASE}/apercu`, label: "Aperçu", icon: Gauge, testId: "subtab-fuel-overview" },
      { to: `${BASE}/transactions`, label: "Transactions", icon: ReceiptText, testId: "subtab-fuel-transactions" },
      { to: `${BASE}/cartes`, label: "Cartes carburant", icon: CreditCard, testId: "subtab-fuel-cards" },
      ...(role === "manager" || isAdmin
        ? [{ to: `${BASE}/rapprochements`, label: "Rapprochements", icon: GitMerge, testId: "subtab-fuel-matching" }] : []),
      { to: `${BASE}/decomptes`, label: "Décomptes", icon: FileCheck2, testId: "subtab-fuel-statements" },
      ...(isAdmin ? [{ to: `${BASE}/importations`, label: "Importations", icon: Upload, testId: "subtab-fuel-imports" }] : []),
      ...(isAdmin ? [{ to: `${BASE}/parametres`, label: "Paramètres", icon: Settings2, testId: "subtab-fuel-settings" }] : []),
    ];
  }

  return (
    <div data-testid="fuel-page" className="space-y-4">
      {role !== "driver" && (
        <p className="text-xs text-slate-500">
          Approvisionnements — achats de carburant et de recharge (cartes, transactions, décomptes).
        </p>
      )}
      <SubTabs tabs={tabs} />
      <Outlet />
    </div>
  );
}
