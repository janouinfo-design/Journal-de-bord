import { Outlet } from "react-router-dom";
import SubTabs from "@/components/layout/SubTabs";
import { useAuth } from "@/contexts/AuthContext";
import { Users, Eye } from "lucide-react";

export default function AdministrationLayout() {
  const { user } = useAuth();
  const isAdmin = ["admin", "superadmin"].includes(user?.role);
  const tabs = [
    ...(isAdmin ? [{ to: "/livre/administration/utilisateurs", label: "Utilisateurs", icon: Users, testId: "subtab-team-users" }] : []),
    ...(isAdmin ? [{ to: "/livre/administration/apercus", label: "Aperçus", icon: Eye, testId: "subtab-team-impersonation" }] : []),
  ];
  return (
    <div data-testid="administration-page" className="space-y-5">
      <div>
        <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400 font-semibold">Administration</p>
        <h1 className="text-2xl font-semibold text-slate-900">Utilisateurs & accès</h1>
        <p className="text-sm text-slate-500 mt-1">
          « Utilisateurs » gère les accès à l'application. La gestion des chauffeurs se trouve
          désormais dans le domaine Conducteurs.
        </p>
      </div>
      <SubTabs tabs={tabs} />
      <Outlet />
    </div>
  );
}
