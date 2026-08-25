import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { Scale, Loader2 } from "lucide-react";

/* Paramètres du rapprochement achats ↔ consommation.
   Aucune valeur par défaut métier — null = aucun seuil (mode diagnostic).
   Le seuil ne s'applique QUE sur les consommations MESURÉES. Alertes désactivées. */
export default function ReconciliationSettingsCard() {
  const [pct, setPct] = useState("");
  const [liters, setLiters] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/livre/energy/reconciliation/settings")
      .then(r => {
        setPct(r.data.threshold_percent ?? "");
        setLiters(r.data.threshold_liters ?? "");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const configured = pct !== "" || liters !== "";

  async function save() {
    setSaving(true);
    try {
      const payload = {
        threshold_percent: pct === "" ? null : Number(pct),
        threshold_liters: liters === "" ? null : Number(liters),
      };
      await api.put("/livre/energy/reconciliation/settings", payload);
      const { data } = await api.get("/livre/energy/reconciliation/settings");
      setPct(data.threshold_percent ?? "");
      setLiters(data.threshold_liters ?? "");
      toast.success("Seuils de rapprochement enregistrés");
    } catch (e) {
      const detail = e?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Erreur lors de l'enregistrement");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="settings-recon-card">
      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Énergie & carburant</p>
      <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2 mt-0.5">
        <Scale className="w-4 h-4 text-[#2196F3]" /> Rapprochement achats ↔ consommation
      </h2>
      <p className="text-xs text-slate-500 mt-1">
        Utilisé uniquement pour les consommations <strong>mesurées</strong>. Les valeurs estimées,
        de référence ou indisponibles ne déclenchent jamais le statut « À contrôler ».
        Alertes automatiques : <strong>désactivées</strong>.
      </p>
      {loading ? (
        <div className="py-6 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4 max-w-lg">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Seuil d'écart (%)</p>
              <Input type="number" min="0.1" max="100" step="0.1" placeholder="—"
                     value={pct} onChange={(e) => setPct(e.target.value)}
                     data-testid="settings-recon-threshold-pct" />
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">Seuil absolu (L)</p>
              <Input type="number" min="0.1" step="0.1" placeholder="—"
                     value={liters} onChange={(e) => setLiters(e.target.value)}
                     data-testid="settings-recon-threshold-liters" />
            </div>
          </div>
          <div className="flex items-center justify-between gap-3 mt-4 flex-wrap">
            <p className="text-xs" data-testid="settings-recon-status">
              {configured ? (
                <span className="text-emerald-700">
                  Seuil configuré — statut « À contrôler » possible sur les écarts mesurés. Aucune alerte envoyée.
                </span>
              ) : (
                <span className="text-slate-500">
                  Aucun seuil configuré — rapprochement en mode diagnostic.
                </span>
              )}
            </p>
            <Button size="sm" onClick={save} disabled={saving}
                    className="bg-[#2196F3] hover:bg-[#1976D2] text-white"
                    data-testid="settings-recon-save">
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "Enregistrer"}
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}
