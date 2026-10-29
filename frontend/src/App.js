import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import ProtectedRoute from "@/components/layout/ProtectedRoute";
import AppLayout from "@/components/layout/AppLayout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import HistoryPage from "@/pages/HistoryPage";
import TaxSwissPage from "@/pages/TaxSwissPage";
import SettingsPage from "@/pages/SettingsPage";
import IdentificationPage from "@/pages/IdentificationPage";
import DriverConsolePage from "@/pages/DriverConsolePage";
import FinesPage from "@/pages/FinesPage";
import FinesDashboardPage from "@/pages/FinesDashboardPage";
import DriverFinesPage from "@/pages/DriverFinesPage";
import AdministrationLayout from "@/pages/AdministrationLayout";
import TeamUsersPage from "@/pages/TeamUsersPage";
import TeamDriversPage from "@/pages/TeamDriversPage";
import VehicleOdometerPage from "@/pages/VehicleOdometerPage";
import TeamImpersonationPage from "@/pages/TeamImpersonationPage";
import InvitationPage from "@/pages/InvitationPage";
import AdminTenantsPage from "@/pages/AdminTenantsPage";
import AdminUsersPage from "@/pages/AdminUsersPage";
import AdminAuditPage from "@/pages/AdminAuditPage";
import ImpersonationBanner from "@/components/layout/ImpersonationBanner";
import FuelLayout from "@/pages/fuel/FuelLayout";
import FuelOverviewPage from "@/pages/fuel/FuelOverviewPage";
import FuelCardsPage from "@/pages/fuel/FuelCardsPage";
import FuelTransactionsPage from "@/pages/fuel/FuelTransactionsPage";
import FuelMatchingPage from "@/pages/fuel/FuelMatchingPage";
import FuelImportsPage from "@/pages/fuel/FuelImportsPage";
import FuelSettingsPage from "@/pages/fuel/FuelSettingsPage";
import FuelMyTransactionsPage from "@/pages/fuel/FuelMyTransactionsPage";
import FuelStatementsPage from "@/pages/fuel/FuelStatementsPage";
import FuelStatementDetailPage from "@/pages/fuel/FuelStatementDetailPage";
import FuelAnomaliesPage from "@/pages/fuel/FuelAnomaliesPage";
import EnergyLayout from "@/pages/energy/EnergyLayout";
import EnergyOverviewPage from "@/pages/energy/EnergyOverviewPage";
import EnergyConsumptionPage from "@/pages/energy/EnergyConsumptionPage";
import EnergyReconciliationPage from "@/pages/energy/EnergyReconciliationPage";
import DriversLayout from "@/pages/drivers/DriversLayout";
import DriversOverviewPage from "@/pages/drivers/DriversOverviewPage";
import EcoDrivingPage from "@/pages/drivers/EcoDrivingPage";
import { Toaster } from "@/components/ui/sonner";

function FuelIndexRedirect() {
  const { user } = useAuth();
  return <Navigate to={user?.role === "driver"
    ? "/livre/energie/approvisionnements/mes-transactions"
    : "/livre/energie/approvisionnements/apercu"} replace />;
}

function EnergyIndexRedirect() {
  const { user } = useAuth();
  return <Navigate to={user?.role === "driver"
    ? "/livre/energie/approvisionnements/mes-transactions"
    : "/livre/energie/apercu"} replace />;
}

/* Anciennes URL /livre/carburant/* → nouvelle arborescence Énergie & carburant */
function LegacyFuelRedirect() {
  const location = useLocation();
  let p = location.pathname.replace("/livre/carburant", "/livre/energie/approvisionnements");
  p = p.replace("/livre/energie/approvisionnements/anomalies", "/livre/energie/anomalies");
  return <Navigate to={p + location.search} replace />;
}

function AdministrationIndex() {
  const { can } = useAuth();
  return <Navigate to={can("users.view")
    ? "/livre/administration/utilisateurs" : "/livre/conducteurs/chauffeurs"} replace />;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <ImpersonationBanner />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/invitation" element={<InvitationPage />} />
          <Route
            path="/livre"
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/livre/dashboard" replace />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="history/pro" element={<HistoryPage kind="pro" />} />
            <Route path="history/perso" element={<HistoryPage kind="perso" />} />
            <Route path="reports/pro" element={<Navigate to="/livre/history/pro" replace />} />
            <Route path="reports/perso" element={<Navigate to="/livre/history/perso" replace />} />
            <Route path="reports/tax-swiss" element={<TaxSwissPage />} />

            {/* Legacy : Identification est désormais dans le domaine Conducteurs */}
            <Route path="identification" element={<Navigate to="/livre/conducteurs/identification" replace />} />

            {/* Domaine Conducteurs */}
            <Route path="conducteurs" element={
              <ProtectedRoute module="drivers" perms={["drivers.view"]}>
                <DriversLayout />
              </ProtectedRoute>
            }>
              <Route index element={<Navigate to="/livre/conducteurs/vue-densemble" replace />} />
              <Route path="vue-densemble" element={<DriversOverviewPage />} />
              <Route path="chauffeurs" element={<TeamDriversPage />} />
              <Route path="identification" element={
                <ProtectedRoute perms={["identification.view"]}><IdentificationPage /></ProtectedRoute>} />
              <Route path="sessions" element={
                <ProtectedRoute perms={["identification.view"]}><IdentificationPage view="sessions" /></ProtectedRoute>} />
              <Route path="eco-conduite" element={<EcoDrivingPage />} />
            </Route>

            <Route path="amendes" element={
              <ProtectedRoute module="fines" perms={["fines.view"]}>
                <FinesPage />
              </ProtectedRoute>
            } />
            <Route path="amendes/dashboard" element={
              <ProtectedRoute module="fines" perms={["fines.view"]}>
                <FinesDashboardPage />
              </ProtectedRoute>
            } />
            <Route path="mes-amendes" element={
              <ProtectedRoute module="fines" perms={["fines.view_self", "fines.view"]}><DriverFinesPage /></ProtectedRoute>} />

            {/* Legacy : le module Carburant vit sous Énergie & carburant > Approvisionnements */}
            <Route path="carburant/*" element={<LegacyFuelRedirect />} />

            {/* Domaine Énergie & carburant */}
            <Route path="energie" element={<EnergyLayout />}>
              <Route index element={<EnergyIndexRedirect />} />
              <Route path="apercu" element={
                <ProtectedRoute module="energy" perms={["energy.view"]}><EnergyOverviewPage /></ProtectedRoute>} />
              <Route path="consommations" element={
                <ProtectedRoute module="energy" perms={["energy.view"]}><EnergyConsumptionPage /></ProtectedRoute>} />
              <Route path="rapprochement" element={
                <ProtectedRoute module="energy" perms={["energy.view"]}><EnergyReconciliationPage /></ProtectedRoute>} />
              <Route path="anomalies" element={
                <ProtectedRoute module="fuel" perms={["fuel.view"]}><FuelAnomaliesPage /></ProtectedRoute>} />
              <Route path="approvisionnements" element={<FuelLayout />}>
                <Route index element={<FuelIndexRedirect />} />
                <Route path="apercu" element={
                  <ProtectedRoute module="fuel" perms={["fuel.view"]}><FuelOverviewPage /></ProtectedRoute>} />
                <Route path="transactions" element={
                  <ProtectedRoute module="fuel" perms={["fuel.view"]}><FuelTransactionsPage /></ProtectedRoute>} />
                <Route path="cartes" element={
                  <ProtectedRoute module="fuel_cards" perms={["fuel_cards.view"]}><FuelCardsPage /></ProtectedRoute>} />
                <Route path="rapprochements" element={
                  <ProtectedRoute module="fuel" perms={["fuel.reconcile"]}><FuelMatchingPage /></ProtectedRoute>} />
                <Route path="decomptes" element={
                  <ProtectedRoute module="fuel" perms={["fuel.view"]}><FuelStatementsPage /></ProtectedRoute>} />
                <Route path="decomptes/:id" element={
                  <ProtectedRoute module="fuel" perms={["fuel.view"]}><FuelStatementDetailPage /></ProtectedRoute>} />
                <Route path="importations" element={
                  <ProtectedRoute module="fuel" perms={["fuel.import"]}><FuelImportsPage /></ProtectedRoute>} />
                <Route path="parametres" element={
                  <ProtectedRoute module="fuel" perms={["fuel.admin"]}><FuelSettingsPage /></ProtectedRoute>} />
                <Route path="mes-transactions" element={
                  <ProtectedRoute roles={["driver", "admin", "manager"]} module="fuel"><FuelMyTransactionsPage /></ProtectedRoute>} />
              </Route>
            </Route>

            <Route path="administration" element={
              <ProtectedRoute perms={["users.view", "users.impersonate", "vehicles.admin"]}>
                <AdministrationLayout />
              </ProtectedRoute>
            }>
              <Route index element={<AdministrationIndex />} />
              <Route path="utilisateurs" element={
                <ProtectedRoute perms={["users.view"]}><TeamUsersPage /></ProtectedRoute>} />
              {/* Legacy : la liste des chauffeurs vit dans le domaine Conducteurs */}
              <Route path="chauffeurs" element={<Navigate to="/livre/conducteurs/chauffeurs" replace />} />
              <Route path="kilometrage" element={
                <ProtectedRoute perms={["vehicles.admin"]}><VehicleOdometerPage /></ProtectedRoute>} />
              <Route path="apercus" element={
                <ProtectedRoute perms={["users.impersonate"]}><TeamImpersonationPage /></ProtectedRoute>} />
            </Route>
            <Route path="settings" element={
              <ProtectedRoute perms={["settings.view"]}>
                <SettingsPage />
              </ProtectedRoute>
            } />
          </Route>
          <Route path="/driver" element={
            <ProtectedRoute roles={["admin", "manager", "driver"]} module="drivers">
              <DriverConsolePage />
            </ProtectedRoute>
          } />
          <Route
            path="/admin"
            element={
              <ProtectedRoute roles={["superadmin"]}>
                <AppLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/admin/clients" replace />} />
            <Route path="clients" element={<AdminTenantsPage />} />
            <Route path="utilisateurs" element={<AdminUsersPage />} />
            <Route path="audit" element={<AdminAuditPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/livre/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster richColors position="top-right" />
    </AuthProvider>
  );
}

export default App;
