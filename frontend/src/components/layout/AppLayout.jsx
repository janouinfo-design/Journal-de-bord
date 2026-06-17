import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { TEST_IDS } from "@/constants/testIds";
import {
  LayoutDashboard, Briefcase, User, FileText, Settings,
  LogOut, Bell, Map, Receipt, Building2, ChevronRight, Bluetooth, Smartphone,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const PRIMARY_NAV = [
  { icon: Building2, label: "Organisation", path: "#" },
  { icon: Map, label: "Tracking", path: "#" },
  { icon: FileText, label: "Rapports", path: "/livre/dashboard", active: true },
  { icon: Settings, label: "Réglages", path: "/livre/settings" },
];

const NAV_SECTIONS = [
  {
    label: "Consulter",
    items: [
      { to: "/livre/dashboard", label: "Tableau de bord", icon: LayoutDashboard, testId: TEST_IDS.layout.navDashboard },
      { to: "/livre/history/pro", label: "Historique professionnel", icon: Briefcase, testId: TEST_IDS.layout.navHistoryPro },
      { to: "/livre/history/perso", label: "Historique personnel", icon: User, testId: TEST_IDS.layout.navHistoryPerso },
    ],
  },
  {
    label: "Générer",
    items: [
      { to: "/livre/reports/tax-swiss", label: "Rapport fiscal suisse", icon: Receipt, testId: TEST_IDS.layout.navTaxSwiss },
    ],
  },
  {
    label: "Identification BLE",
    items: [
      { to: "/livre/identification", label: "Identification chauffeurs", icon: Bluetooth, testId: "nav-identification", adminOnly: true },
      { to: "/driver", label: "Console chauffeur (PWA)", icon: Smartphone, testId: "nav-driver-console" },
    ],
  },
  {
    label: "Configuration",
    items: [
      { to: "/livre/settings", label: "Paramètres du livre", icon: Settings, testId: TEST_IDS.layout.navSettings },
    ],
  },
];

const ROLE_LABEL = { admin: "Administrateur", manager: "Gestionnaire", driver: "Chauffeur" };

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function onLogout() {
    await logout();
    navigate("/login");
  }

  const initials = (user?.name || user?.email || "?")
    .split(" ").map(s => s[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="min-h-screen flex bg-[#F4F6F8] font-[IBM_Plex_Sans,sans-serif]">
      {/* Primary dark sidebar */}
      <aside data-testid={TEST_IDS.layout.sidebarPrimary} className="w-16 bg-slate-900 flex flex-col items-center py-4 gap-2 shrink-0">
        <div className="text-[10px] text-slate-500 font-mono mb-2">LT</div>
        {PRIMARY_NAV.map((it) => (
          <button
            key={it.label}
            title={it.label}
            className={`w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${
              it.active ? "text-[#2196F3] bg-slate-800" : "text-slate-400 hover:text-white hover:bg-slate-800"
            }`}
          >
            <it.icon className="w-[18px] h-[18px]" />
          </button>
        ))}
      </aside>

      {/* Secondary white sidebar */}
      <aside data-testid={TEST_IDS.layout.sidebarSecondary} className="w-64 bg-white border-r border-slate-200 flex flex-col shrink-0">
        <div className="px-5 py-5 border-b border-slate-100">
          <div data-testid={TEST_IDS.layout.headerLogo} className="text-xl font-semibold tracking-tight">
            Logi<span className="text-[#E53935]">t</span>rak
          </div>
          <p className="text-[10px] uppercase tracking-[0.18em] text-slate-400 mt-1">Livre de Bord</p>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <p className="px-3 text-[10px] uppercase tracking-[0.15em] text-slate-400 mb-2 font-semibold">
                {section.label}
              </p>
              <div className="space-y-0.5">
                {section.items.filter(it => !it.adminOnly || user?.role === "admin" || user?.role === "manager").map((it) => (
                  <NavLink
                    key={it.to}
                    to={it.to}
                    data-testid={it.testId}
                    className={({ isActive }) =>
                      `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                        isActive
                          ? "text-[#2196F3] bg-blue-50"
                          : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                      }`
                    }
                  >
                    <it.icon className="w-4 h-4" />
                    <span className="truncate">{it.label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-3 text-[11px] text-slate-400">
          v1.0 · Données LOGITRAK
        </div>
      </aside>

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-slate-500">Logitrak</span>
            <ChevronRight className="w-3 h-3 text-slate-400" />
            <span className="text-slate-500">Rapports</span>
            <ChevronRight className="w-3 h-3 text-slate-400" />
            <span className="text-slate-900 font-medium">Livre de bord</span>
          </div>
          <div className="flex items-center gap-3">
            <button className="w-9 h-9 rounded-md hover:bg-slate-100 flex items-center justify-center text-slate-500 relative">
              <Bell className="w-[18px] h-[18px]" />
              <span className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full bg-[#E53935]" />
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button data-testid={TEST_IDS.layout.userMenu} className="flex items-center gap-2.5 hover:bg-slate-50 rounded-md pl-2 pr-3 py-1.5 transition-colors">
                  <Avatar className="w-8 h-8 bg-[#2196F3]">
                    <AvatarFallback className="bg-[#2196F3] text-white text-xs font-medium">{initials}</AvatarFallback>
                  </Avatar>
                  <div className="text-left leading-tight">
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
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="max-w-[1600px] mx-auto p-6 lg:p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
