import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/contexts/AuthContext";
import ProtectedRoute from "@/components/layout/ProtectedRoute";
import AppLayout from "@/components/layout/AppLayout";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import HistoryPage from "@/pages/HistoryPage";
import ReportsPage from "@/pages/ReportsPage";
import TaxSwissPage from "@/pages/TaxSwissPage";
import SettingsPage from "@/pages/SettingsPage";
import { Toaster } from "@/components/ui/sonner";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
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
            <Route path="reports/pro" element={<ReportsPage kind="pro" />} />
            <Route path="reports/perso" element={<ReportsPage kind="perso" />} />
            <Route path="reports/tax-swiss" element={<TaxSwissPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/livre/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster richColors position="top-right" />
    </AuthProvider>
  );
}

export default App;
