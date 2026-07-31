import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
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
import { Toaster } from "@/components/ui/sonner";

function FuelIndexRedirect() {
  const { user } = useAuth();
  return <Navigate to={user?.role === "driver"
    ? "/livre/carburant/mes-transactions" : "/livre/carburant/apercu"} replace />;
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
            <Route path="identification" element={
              <ProtectedRoute roles={["admin", "manager"]}>
                <IdentificationPage />
              </ProtectedRoute>
            } />
            <Route path="amendes" element={
              <ProtectedRoute roles={["admin", "manager", "lecture_seule"]}>
                <FinesPage />
              </ProtectedRoute>
            } />
            <Route path="amendes/dashboard" element={
              <ProtectedRoute roles={["admin", "manager", "lecture_seule"]}>
                <FinesDashboardPage />
              </ProtectedRoute>
            } />
            <Route path="mes-amendes" element={<DriverFinesPage />} />
            <Route path="carburant" element={<FuelLayout />}>
              <Route index element={<FuelIndexRedirect />} />
              <Route path="apercu" element={
                <ProtectedRoute roles={["admin", "manager", "lecture_seule"]}><FuelOverviewPage /></ProtectedRoute>} />
              <Route path="transactions" element={
                <ProtectedRoute roles={["admin", "manager", "lecture_seule"]}><FuelTransactionsPage /></ProtectedRoute>} />
              <Route path="cartes" element={
                <ProtectedRoute roles={["admin", "manager", "lecture_seule"]}><FuelCardsPage /></ProtectedRoute>} />
              <Route path="rapprochements" element={
                <ProtectedRoute roles={["admin", "manager"]}><FuelMatchingPage /></ProtectedRoute>} />
              <Route path="decomptes" element={
                <ProtectedRoute roles={["admin", "manager", "lecture_seule"]}><FuelStatementsPage /></ProtectedRoute>} />
              <Route path="decomptes/:id" element={
                <ProtectedRoute roles={["admin", "manager", "lecture_seule"]}><FuelStatementDetailPage /></ProtectedRoute>} />
              <Route path="importations" element={
                <ProtectedRoute roles={["admin"]}><FuelImportsPage /></ProtectedRoute>} />
              <Route path="parametres" element={
                <ProtectedRoute roles={["admin"]}><FuelSettingsPage /></ProtectedRoute>} />
              <Route path="mes-transactions" element={
                <ProtectedRoute roles={["driver", "admin", "manager"]}><FuelMyTransactionsPage /></ProtectedRoute>} />
            </Route>
            <Route path="administration" element={
              <ProtectedRoute roles={["admin"]}>
                <AdministrationLayout />
              </ProtectedRoute>
            }>
              <Route index element={<Navigate to="/livre/administration/utilisateurs" replace />} />
              <Route path="utilisateurs" element={<TeamUsersPage />} />
              <Route path="chauffeurs" element={<TeamDriversPage />} />
              <Route path="apercus" element={<TeamImpersonationPage />} />
            </Route>
            <Route path="settings" element={
              <ProtectedRoute roles={["admin", "manager"]}>
                <SettingsPage />
              </ProtectedRoute>
            } />
          </Route>
          <Route path="/driver" element={
            <ProtectedRoute roles={["admin", "manager", "driver"]}>
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
