import { NavLink, Outlet, useNavigate, Navigate } from "react-router-dom";

function NavigateToAdmin() {
  return <Navigate to="/admin/clients" replace />;
}
import { useAuth } from "@/contexts/AuthContext";
import { TEST_IDS } from "@/constants/testIds";
import {
  Avatar, AvatarFallback,
} from "@/components/ui/avatar";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  LayoutDashboard, Briefcase, ShieldAlert, Bluetooth, Receipt, Fuel,
  Settings, Smartphone, LogOut, Layers, Building2, Users, ScrollText, UserCog,
} from "lucide-react";
import ConflictInbox from "@/components/livre/ConflictInbox";
import TenantSwitcher from "@/components/layout/TenantSwitcher";
import NotificationsBell from "@/components/layout/NotificationsBell";

const ROLE_LABEL = {
  admin: "Administrateur",
  manager: "Gestionnaire flotte",
  driver: "Chauffeur",
  lecture_seule: "Lecture seule",
  superadmin: "Super Admin Logitrak",
};

// Horizontal top-nav tabs. Each item can be restricted by role. When null/undefined
// the item is visible to everyone.
const TABS = [
  { to: "/livre/dashboard",       label: "Tableau de bord", icon: LayoutDashboard, testId: "nav-dashboard" },
  { to: "/livre/history/pro",     label: "Historique",      icon: Briefcase,       testId: "nav-history",       roles: ["admin", "manager", "lecture_seule"],
    matchPrefix: "/livre/history" },
  { to: "/livre/amendes",         label: "Amendes",         icon: ShieldAlert,     testId: "nav-fines",         roles: ["admin", "manager", "lecture_seule"],
    matchPrefix: "/livre/amendes" },
  { to: "/livre/mes-amendes",     label: "Mes amendes",     icon: ShieldAlert,     testId: "nav-my-fines",      roles: ["driver"] },
  { to: "/livre/carburant/apercu", label: "Carburant",      icon: Fuel,            testId: "nav-fuel",          roles: ["admin", "manager", "lecture_seule"],
    matchPrefix: "/livre/carburant" },
  { to: "/livre/carburant/mes-transactions", label: "Mes transactions", icon: Fuel, testId: "nav-my-fuel",     roles: ["driver"],
    matchPrefix: "/livre/carburant" },
  { to: "/livre/identification",  label: "Identification",  icon: Bluetooth,       testId: "nav-identification", roles: ["admin", "manager"] },
  { to: "/driver",                label: "Console PWA",     icon: Smartphone,      testId: "nav-driver-console", roles: ["admin", "manager", "driver"] },
  { to: "/livre/reports/tax-swiss", label: "Rapports",      icon: Receipt,         testId: "nav-reports",       roles: ["admin", "manager", "lecture_seule"] },
  { to: "/livre/administration",  label: "Administration",  icon: UserCog,         testId: "nav-administration", roles: ["admin"] },
  { to: "/livre/settings",        label: "Paramètres",      icon: Settings,        testId: TEST_IDS.layout.navSettings, roles: ["admin", "manager"] },
  { to: "/admin/clients",         label: "Clients",         icon: Building2,       testId: "nav-admin-tenants", roles: ["superadmin"] },
  { to: "/admin/utilisateurs",    label: "Utilisateurs",    icon: Users,           testId: "nav-admin-users",   roles: ["superadmin"] },
  { to: "/admin/audit",           label: "Audit",           icon: ScrollText,      testId: "nav-admin-audit",   roles: ["superadmin"] },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const initials = (user?.name || user?.email || "?")
    .split(" ").map((s) => s[0]).slice(0, 2).join("").toUpperCase();

  // Superadmin sans client sélectionné → redirection vers l'écran Clients
  const needsAdminRedirect =
    user?.role === "superadmin" &&
    !localStorage.getItem("sa_tenant_id") &&
    window.location.pathname.startsWith("/livre");
  if (needsAdminRedirect) {
    return <NavigateToAdmin />;
  }

  function onLogout() { logout(); navigate("/login"); }

  const isSuperAdmin = user?.role === "superadmin";
  const saTenant = isSuperAdmin ? localStorage.getItem("sa_tenant_id") : null;

  const visibleTabs = TABS.filter((t) => {
    if (isSuperAdmin) {
      if (t.roles?.includes("superadmin")) return true;
      // Onglets métier visibles seulement quand un client est sélectionné
      return !!saTenant && (!t.roles || t.roles.includes("admin"));
    }
    return !t.roles || t.roles.includes(user?.role);
  });

  return (
    <div className="min-h-screen flex flex-col bg-[#F4F6F8] font-[IBM_Plex_Sans,sans-serif]">
      {/* Top bar with logo + user menu */}
      <header data-testid={TEST_IDS.layout.sidebarSecondary}
              className="bg-white border-b border-slate-200 shrink-0 sticky top-0 z-30">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between px-6 lg:px-8 pt-4">
          {/* Logo block */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-slate-900 flex items-center justify-center text-white">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <div data-testid={TEST_IDS.layout.headerLogo}
                   className="text-lg font-semibold tracking-tight text-slate-900 leading-tight">
                LogiTrak
              </div>
              <p className="text-[9px] uppercase tracking-[0.22em] text-slate-400 font-semibold leading-tight">
                {ROLE_LABEL[user?.role]?.toUpperCase() || "FLEET"}
              </p>
            </div>
          </div>

          {/* Right actions: tenant switcher (superadmin) + conflict inbox + user menu */}
          <div className="flex items-center gap-3">
            {isSuperAdmin && <TenantSwitcher />}
            <NotificationsBell />
            {(user?.role === "admin" || user?.role === "manager") && <ConflictInbox />}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button data-testid={TEST_IDS.layout.userMenu}
                        className="flex items-center gap-2.5 hover:bg-slate-50 rounded-md pl-2 pr-3 py-1.5 transition-colors">
                  <Avatar className="w-8 h-8 bg-[#2196F3]">
                    <AvatarFallback className="bg-[#2196F3] text-white text-xs font-medium">{initials}</AvatarFallback>
                  </Avatar>
                  <div className="text-left leading-tight hidden sm:block">
                    <p className="text-sm font-medium text-slate-800">{user?.name}</p>
                    <p className="text-[11px] text-slate-500">{ROLE_LABEL[user?.role] || user?.role}</p>
                  </div>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <p className="text-sm">{user?.email}</p>
                  <p className="text-xs text-slate-500 font-normal mt-0.5">{ROLE_LABEL[user?.role]}</p>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  data-testid={TEST_IDS.layout.logout}
                  onClick={onLogout}
                  className="text-red-600 focus:text-red-600 cursor-pointer"
                >
                  <LogOut className="w-4 h-4 mr-2" /> Déconnexion
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Horizontal nav tabs — scrollable on mobile */}
        <nav className="max-w-[1600px] mx-auto px-6 lg:px-8 mt-3">
          <div className="flex items-center gap-1 overflow-x-auto no-scrollbar -mb-px"
               data-testid="app-top-nav">
            {visibleTabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  end={!tab.matchPrefix}
                  data-testid={tab.testId}
                  className={({ isActive }) => {
                    const active = isActive || (tab.matchPrefix && window.location.pathname.startsWith(tab.matchPrefix));
                    return [
                      "flex items-center gap-2 px-3.5 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2",
                      active
                        ? "text-slate-900 border-slate-900"
                        : "text-slate-500 border-transparent hover:text-slate-800",
                    ].join(" ");
                  }}
                >
                  <Icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                </NavLink>
              );
            })}
          </div>
        </nav>
      </header>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-[1600px] mx-auto p-6 lg:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
