import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { BellOff, Loader2, Lock, X } from "lucide-react";

/* Préparation des alertes « À contrôler » — AUCUN envoi (e-mail/SMS/push).
   Verrou backend : activation refusée (409) tant que la campagne REAL ENERGY
   n'est pas validée pour ce client. Les destinataires sont stockés pour plus
   tard, sans aucun envoi. Chaque modification est auditée. */
export default function ReconciliationAlertsCard() {
  const [cfg, setCfg] = useState(null);
  const [candidates, setCandidates] = useState(0);
  const [email, setEmail] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/livre/energy/reconciliation/alerts/config")
      .then(r => setCfg(r.data)).catch(() => {});
    api.get("/livre/energy/reconciliation/alerts/candidates")
      .then(r => setCandidates(r.data.total)).catch(() => {});
  }, []);

  async function saveRecipients(next) {
    setSaving(true);
    try {
      const { data } = await api.put("/livre/energy/reconciliation/alerts/config",
        { recipients: next });
      setCfg(data);
      setEmail("");
      toast.success("Destinataires enregistrés — aucun message envoyé");
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Erreur lors de l'enregistrement");
    } finally {
      setSaving(false);
    }
  }

  if (!cfg) {
    return (
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="settings-alerts-card">
        <div className="py-6 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div>
      </Card>
    );
  }

  const recipients = cfg.recipients || [];
  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="settings-alerts-card">
      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Énergie & carburant</p>
      <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2 mt-0.5">
        <BellOff className="w-4 h-4 text-slate-400" /> Alertes « À contrôler » — préparation
      </h2>

      <div data-testid="settings-alerts-banner"
           className="mt-3 bg-slate-100 border border-slate-200 text-slate-700 rounded-md px-3 py-2 text-xs font-semibold">
        APERÇU — AUCUN MESSAGE ENVOYÉ (e-mail, SMS et push désactivés)
      </div>

      <div className="flex items-center justify-between gap-3 mt-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Switch checked={false} disabled data-testid="settings-alerts-switch" />
          <span className="text-sm text-slate-600">Activer les alertes automatiques</span>
        </div>
        <Badge variant="outline" data-testid="settings-alerts-lock"
               className="bg-rose-50 text-rose-600 border-rose-200 text-[10px] px-2 py-0.5 flex items-center gap-1">
          <Lock className="w-3 h-3" /> Verrouillé — campagne REAL ENERGY non validée
        </Badge>
      </div>
      <p className="text-xs text-slate-500 mt-2" data-testid="settings-alerts-lock-reason">
        {cfg.lock_reason} Le backend refuse toute activation tant que{" "}
        <code className="font-mono text-[10px]">real_energy_validated</code> est faux pour ce client.
      </p>

      <div className="mt-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">
          Destinataires futurs (aucun envoi)
        </p>
        <div className="flex items-center gap-2 max-w-md">
          <Input type="email" placeholder="email@exemple.ch" value={email}
                 onChange={(e) => setEmail(e.target.value)}
                 data-testid="settings-alerts-recipient-input" />
          <Button size="sm" variant="outline" disabled={saving || !email}
                  onClick={() => saveRecipients([...recipients, email])}
                  data-testid="settings-alerts-add-recipient">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "Ajouter"}
          </Button>
        </div>
        {recipients.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2" data-testid="settings-alerts-recipients">
            {recipients.map(r => (
              <Badge key={r} variant="outline"
                     className="bg-slate-50 text-slate-600 border-slate-200 text-[10px] px-1.5 py-0.5 flex items-center gap-1">
                {r}
                <button onClick={() => saveRecipients(recipients.filter(x => x !== r))}
                        data-testid={`settings-alerts-remove-${r}`}
                        className="text-slate-400 hover:text-rose-500">
                  <X className="w-3 h-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      <p className="text-xs text-slate-500 mt-4" data-testid="settings-alerts-candidates-count">
        Candidats d'alerte enregistrés (aperçu, jamais envoyés) : <strong>{candidates}</strong>{" "}
        — anti-doublonnage par véhicule + période. Chaque modification de cette configuration est auditée.
      </p>
    </Card>
  );
}
