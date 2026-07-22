import { useEffect } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Eye, LogOut, CheckCircle2, AlertTriangle } from "lucide-react";

const ROLE_LABEL = { admin: "Administrateur", manager: "Gestionnaire", driver: "Chauffeur", lecture_seule: "Lecture seule" };

export default function ImpersonationBanner() {
  const { user, endImpersonation, impersonationEnded, impersonationError, clearImpersonationError } = useAuth();
  const active = !!user?.impersonated_by && !impersonationEnded;

  useEffect(() => {
    if (!active) return;
    document.body.style.paddingBottom = "64px";
    return () => { document.body.style.paddingBottom = ""; };
  }, [active]);

  if (impersonationEnded) {
    return (
      <div data-testid="impersonation-ended-screen"
           className="fixed inset-0 z-[200] bg-slate-900/95 flex items-center justify-center p-6">
        <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-8 text-center space-y-4">
          <CheckCircle2 className="w-12 h-12 text-emerald-500 mx-auto" />
          <h2 className="text-lg font-semibold text-slate-900">Aperçu terminé</h2>
          <p className="text-sm text-slate-500">
            Vous pouvez maintenant fermer cet onglet et retourner à votre session administrateur.
          </p>
          <Button data-testid="impersonation-back-dashboard" variant="outline" className="w-full"
                  onClick={() => window.location.replace("/livre/dashboard")}>
            Ou continuer ici avec mon compte administrateur
          </Button>
        </div>
      </div>
    );
  }

  if (impersonationError) {
    return (
      <div data-testid="impersonation-error-banner"
           className="fixed top-0 inset-x-0 z-[150] bg-red-600 text-white">
        <div className="max-w-[1600px] mx-auto px-4 py-2 flex items-center justify-between gap-3 text-sm">
          <span className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            Aperçu impossible : {impersonationError}
          </span>
          <button data-testid="impersonation-error-close" onClick={clearImpersonationError}
                  className="underline underline-offset-2 shrink-0">Fermer</button>
        </div>
      </div>
    );
  }

  if (!active) return null;

  return (
    <div data-testid="impersonation-banner"
         className="fixed bottom-0 inset-x-0 z-[100] bg-amber-500 text-slate-900 shadow-[0_-4px_16px_rgba(0,0,0,0.25)]">
      <div className="max-w-[1600px] mx-auto px-4 py-2.5 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5 text-sm min-w-0">
          <Eye className="w-4 h-4 shrink-0" />
          <span className="truncate">
            <strong>Aperçu Utilisateur</strong> — vous voyez l'application en tant que{" "}
            <strong>{user.name || user.email}</strong> ({ROLE_LABEL[user.role] || user.role})
            <span className="hidden md:inline text-amber-900/80"> · session ouverte par {user.impersonated_by.email}</span>
          </span>
        </div>
        <Button data-testid="impersonation-exit-btn" size="sm"
                className="bg-slate-900 text-white hover:bg-slate-800 h-8 shrink-0"
                onClick={endImpersonation}>
          <LogOut className="w-3.5 h-3.5 mr-1.5" /> Retour au compte administrateur
        </Button>
      </div>
    </div>
  );
}
