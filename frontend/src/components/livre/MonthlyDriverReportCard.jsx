import { useEffect, useState } from "react";
import { api, downloadBlob } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Download, FileCheck2, Loader2, Mail, X } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

/* Rapport mensuel fiscal chauffeurs — configuration (admin/manager uniquement).
   Aucune logique métier ici : la carte consomme les endpoints
   /livre/reports/monthly-driver/config et /download. */
const STATUS_LABELS = {
  sent: { label: "Envoyé", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  not_sent_smtp_not_configured: { label: "Non envoyé — SMTP non configuré", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  not_sent_no_recipients: { label: "Non envoyé — aucun destinataire", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  error: { label: "Erreur d'envoi", cls: "bg-rose-50 text-rose-600 border-rose-200" },
  already_sent: { label: "Déjà envoyé", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
};

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-CH"); } catch { return iso; }
}

export default function MonthlyDriverReportCard() {
  const { user } = useAuth();
  const [cfg, setCfg] = useState(null);
  const [email, setEmail] = useState("");
  const [month, setMonth] = useState("");
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const canView = user?.role === "admin" || user?.role === "manager";

  useEffect(() => {
    if (!canView) return;
    api.get("/livre/reports/monthly-driver/config")
      .then(r => { setCfg(r.data); setMonth(m => m || r.data.default_month || ""); })
      .catch(() => {});
  }, [canView]);

  if (!canView) return null;

  async function save(patch) {
    setSaving(true);
    try {
      const { data } = await api.put("/livre/reports/monthly-driver/config", patch);
      setCfg(data);
      setEmail("");
      toast.success("Configuration du rapport mensuel enregistrée");
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Erreur lors de l'enregistrement");
    } finally {
      setSaving(false);
    }
  }

  async function download(fmt) {
    if (!month) { toast.error("Choisissez d'abord un mois"); return; }
    setDownloading(fmt);
    try {
      const res = await api.get("/livre/reports/monthly-driver/download",
        { params: { month, format: fmt }, responseType: "blob" });
      downloadBlob(res.data, `rapport_mensuel_fiscal_chauffeurs_${month}.${fmt}`);
    } catch (e) {
      toast.error("Téléchargement impossible");
    } finally {
      setDownloading(null);
    }
  }

  if (!cfg) {
    return (
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="monthly-report-card">
        <div className="py-6 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div>
      </Card>
    );
  }

  const recipients = cfg.recipients || [];
  const lastStatus = cfg.last_send ? (STATUS_LABELS[cfg.last_send.status] || { label: cfg.last_send.status, cls: "bg-slate-50 text-slate-600 border-slate-200" }) : null;

  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="monthly-report-card">
      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Rapports</p>
      <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2 mt-0.5">
        <FileCheck2 className="w-4 h-4 text-[#2196F3]" /> Rapport mensuel fiscal chauffeurs
      </h2>
      <p className="text-xs text-slate-500 mt-1" data-testid="monthly-report-intro">
        Récapitulatif par chauffeur prêt pour la déclaration : km PRO / PRIVÉ, part privée,
        cumul annuel et statut « À compléter » tant qu'il reste des trajets non classifiés.
      </p>

      <div className="flex items-center justify-between gap-3 mt-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Switch checked={cfg.enabled} disabled={saving}
                  onCheckedChange={(v) => save({ enabled: v })}
                  data-testid="monthly-report-toggle" />
          <span className="text-sm text-slate-600">
            Envoi automatique {cfg.enabled ? "activé" : "désactivé"}
          </span>
        </div>
        <Badge variant="outline" data-testid="monthly-report-smtp-status"
               className={`text-[10px] px-2 py-0.5 flex items-center gap-1 ${
                 cfg.smtp_configured
                   ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                   : "bg-amber-50 text-amber-700 border-amber-200"}`}>
          <Mail className="w-3 h-3" /> SMTP {cfg.smtp_configured ? "configuré" : "non configuré"}
        </Badge>
      </div>
      {!cfg.smtp_configured && (
        <p className="text-xs text-slate-500 mt-2" data-testid="monthly-report-smtp-note">
          Sans SMTP, le rapport reste téléchargeable ici chaque mois — seul l'envoi e-mail est sauté.
        </p>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-xs">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Période couverte</p>
          <p className="text-slate-700 mt-0.5" data-testid="monthly-report-period">Mois civil précédent</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Envoi</p>
          <p className="text-slate-700 mt-0.5" data-testid="monthly-report-formats">Le 1er à 06:00 · PDF + XLSX</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Prochain envoi</p>
          <p className="text-slate-700 mt-0.5 font-mono text-[11px]" data-testid="monthly-report-next-run">
            {cfg.enabled ? fmtDate(cfg.next_run) : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Dernier envoi</p>
          {lastStatus ? (
            <div className="mt-0.5 space-y-1" data-testid="monthly-report-last-send">
              <p className="text-slate-700 font-mono text-[11px]">{fmtDate(cfg.last_send.created_at)}</p>
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0.5 ${lastStatus.cls}`}>
                {lastStatus.label}
              </Badge>
            </div>
          ) : (
            <p className="text-slate-500 mt-0.5" data-testid="monthly-report-last-send">Aucun envoi pour l'instant</p>
          )}
        </div>
      </div>

      <div className="mt-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">
          Destinataires ({recipients.length})
        </p>
        <div className="flex items-center gap-2 max-w-md">
          <Input type="email" placeholder="fiduciaire@exemple.ch" value={email}
                 onChange={(e) => setEmail(e.target.value)}
                 data-testid="monthly-report-recipient-input" />
          <Button size="sm" variant="outline" disabled={saving || !email}
                  onClick={() => save({ recipients: [...recipients, email] })}
                  data-testid="monthly-report-add-recipient">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "Ajouter"}
          </Button>
        </div>
        {recipients.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2" data-testid="monthly-report-recipients">
            {recipients.map(r => (
              <Badge key={r} variant="outline"
                     className="bg-slate-50 text-slate-600 border-slate-200 text-[10px] px-1.5 py-0.5 flex items-center gap-1">
                {r}
                <button onClick={() => save({ recipients: recipients.filter(x => x !== r) })}
                        data-testid={`monthly-report-remove-${r}`}
                        className="text-slate-400 hover:text-rose-500">
                  <X className="w-3 h-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="mt-5 border-t border-slate-100 pt-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">
          Téléchargement manuel — mois au choix
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value)}
                 className="w-44 h-9" data-testid="monthly-report-month-input" />
          <Button size="sm" variant="outline" disabled={!!downloading}
                  onClick={() => download("pdf")} data-testid="monthly-report-download-pdf">
            {downloading === "pdf" ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-1.5" />}
            Télécharger PDF
          </Button>
          <Button size="sm" variant="outline" disabled={!!downloading}
                  onClick={() => download("xlsx")} data-testid="monthly-report-download-xlsx">
            {downloading === "xlsx" ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-1.5" />}
            Télécharger XLSX
          </Button>
        </div>
        <p className="text-[10px] text-slate-500 mt-2">
          Le téléchargement fonctionne même si l'envoi automatique est désactivé.
          Aucun montant CHF n'est calculé : le rapport fournit les kilomètres à reporter.
        </p>
      </div>
    </Card>
  );
}
