import { useAuth } from "@/contexts/AuthContext";
import { Navigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

export default function ProtectedRoute({ children, roles }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <Loader2 className="w-6 h-6 animate-spin text-[#2196F3]" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (roles && roles.length > 0 && !roles.includes(user.role)) {
    return <Navigate to="/livre/dashboard" replace />;
  }
  return children;
}
