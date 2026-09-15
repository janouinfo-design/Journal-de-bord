import { Card } from "@/components/ui/card";
import { Leaf } from "lucide-react";

export default function EcoDrivingPage() {
  return (
    <div data-testid="eco-driving-page" className="max-w-2xl">
      <Card className="bg-white border-slate-200 shadow-sm rounded-md p-8 text-center space-y-3">
        <div className="w-12 h-12 rounded-full bg-slate-50 border border-slate-200 flex items-center justify-center mx-auto">
          <Leaf className="w-5 h-5 text-slate-400" />
        </div>
        <h2 className="text-base font-semibold text-slate-800">Éco-conduite — Non disponible</h2>
        <p className="text-sm text-slate-500">
          Les scores d&apos;éco-conduite seront fournis par le <strong>module Énergie</strong> (projet séparé).
          Le Journal n&apos;effectue aucun calcul : cette page affichera les données dès que la dépendance sera connectée.
        </p>
        <p className="text-xs text-slate-400" data-testid="eco-driving-dependency">
          Dépendance manquante : endpoint éco-conduite du contrat Energy → Journal.
        </p>
      </Card>
    </div>
  );
}
