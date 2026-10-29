import { useAuth } from "@/contexts/AuthContext";
import { Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

// roles : liste blanche legacy (superadmin passe toujours) ; module : module client requis ;
// perms : l'utilisateur doit détenir l'UNE des permissions. Toute condition manquante → dashboard.
export default function ProtectedRoute({ children, roles, perms, module }) {
  const { user, loading, can, hasModule } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (roles && roles.length > 0 && !roles.includes(user.role) && user.role !== "superadmin") {
    return <Navigate to="/livre/dashboard" replace />;
  }
  if (module && !hasModule(module)) return <Navigate to="/livre/dashboard" replace />;
  if (perms && perms.length > 0 && !can(...perms)) return <Navigate to="/livre/dashboard" replace />;
  return children;
}
