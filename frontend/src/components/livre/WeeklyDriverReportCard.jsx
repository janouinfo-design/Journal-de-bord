import { useEffect, useState } from "react";
import { api, downloadBlob } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { CalendarClock, Download, Loader2, Mail, X } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

/* Rapport hebdomadaire chauffeurs — configuration (admin/manager uniquement).
   Aucune logique métier ici : la carte consomme les endpoints
   /livre/reports/weekly-driver/config et /download. */
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

export default function WeeklyDriverReportCard() {
  const { user } = useAuth();
  const [cfg, setCfg] = useState(null);
  const [email, setEmail] = useState("");
  const [week, setWeek] = useState("");
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const canView = user?.role === "admin" || user?.role === "manager";

  useEffect(() => {
    if (!canView) return;
    api.get("/livre/reports/weekly-driver/config")
      .then(r => { setCfg(r.data); setWeek(w => w || r.data.default_week || ""); })
      .catch(() => {});
  }, [canView]);

  if (!canView) return null;

  async function save(patch) {
    setSaving(true);
    try {
      const { data } = await api.put("/livre/reports/weekly-driver/config", patch);
      setCfg(data);
      setEmail("");
      toast.success("Configuration du rapport hebdomadaire enregistrée");
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Erreur lors de l'enregistrement");
    } finally {
      setSaving(false);
    }
  }

  async function download(fmt) {
    if (!week) { toast.error("Choisissez d'abord une semaine"); return; }
    setDownloading(fmt);
    try {
      const res = await api.get("/livre/reports/weekly-driver/download",
        { params: { week, format: fmt }, responseType: "blob" });
      downloadBlob(res.data, `rapport_hebdo_chauffeurs_${week}.${fmt}`);
    } catch (e) {
      toast.error("Téléchargement impossible");
    } finally {
      setDownloading(null);
    }
  }

  if (!cfg) {
    return (
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="weekly-report-card">
        <div className="py-6 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div>
      </Card>
    );
  }

  const recipients = cfg.recipients || [];
  const lastStatus = cfg.last_send ? (STATUS_LABELS[cfg.last_send.status] || { label: cfg.last_send.status, cls: "bg-slate-50 text-slate-600 border-slate-200" }) : null;

  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="weekly-report-card">
      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Rapports</p>
      <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2 mt-0.5">
        <CalendarClock className="w-4 h-4 text-[#2196F3]" /> Rapport hebdomadaire chauffeurs
      </h2>

      <div className="flex items-center justify-between gap-3 mt-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Switch checked={cfg.enabled} disabled={saving}
                  onCheckedChange={(v) => save({ enabled: v })}
                  data-testid="weekly-report-toggle" />
          <span className="text-sm text-slate-600">
            Envoi automatique {cfg.enabled ? "activé" : "désactivé"}
          </span>
        </div>
        <Badge variant="outline" data-testid="weekly-report-smtp-status"
               className={`text-[10px] px-2 py-0.5 flex items-center gap-1 ${
                 cfg.smtp_configured
                   ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                   : "bg-amber-50 text-amber-700 border-amber-200"}`}>
          <Mail className="w-3 h-3" /> SMTP {cfg.smtp_configured ? "configuré" : "non configuré"}
        </Badge>
      </div>
      {!cfg.smtp_configured && (
        <p className="text-xs text-slate-500 mt-2" data-testid="weekly-report-smtp-note">
          Sans SMTP, le rapport est quand même généré chaque lundi et reste téléchargeable ici —
          seul l'envoi e-mail est sauté.
        </p>
      )}

      {/* Infos en lecture seule */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4 text-xs">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Période couverte</p>
          <p className="text-slate-700 mt-0.5" data-testid="weekly-report-period">Semaine précédente — lundi à dimanche</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Formats</p>
          <p className="text-slate-700 mt-0.5" data-testid="weekly-report-formats">PDF + XLSX</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Prochain envoi</p>
          <p className="text-slate-700 mt-0.5 font-mono text-[11px]" data-testid="weekly-report-next-run">
            {cfg.enabled ? fmtDate(cfg.next_run) : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Dernier envoi</p>
          {lastStatus ? (
            <div className="mt-0.5 space-y-1" data-testid="weekly-report-last-send">
              <p className="text-slate-700 font-mono text-[11px]">{fmtDate(cfg.last_send.created_at)}</p>
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0.5 ${lastStatus.cls}`}>
                {lastStatus.label}
              </Badge>
            </div>
          ) : (
            <p className="text-slate-500 mt-0.5" data-testid="weekly-report-last-send">Aucun envoi pour l'instant</p>
          )}
        </div>
      </div>

      {/* Destinataires */}
      <div className="mt-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">
          Destinataires ({recipients.length})
        </p>
        <div className="flex items-center gap-2 max-w-md">
          <Input type="email" placeholder="email@exemple.ch" value={email}
                 onChange={(e) => setEmail(e.target.value)}
                 data-testid="weekly-report-recipient-input" />
          <Button size="sm" variant="outline" disabled={saving || !email}
                  onClick={() => save({ recipients: [...recipients, email] })}
                  data-testid="weekly-report-add-recipient">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "Ajouter"}
          </Button>
        </div>
        {recipients.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2" data-testid="weekly-report-recipients">
            {recipients.map(r => (
              <Badge key={r} variant="outline"
                     className="bg-slate-50 text-slate-600 border-slate-200 text-[10px] px-1.5 py-0.5 flex items-center gap-1">
                {r}
                <button onClick={() => save({ recipients: recipients.filter(x => x !== r) })}
                        data-testid={`weekly-report-remove-${r}`}
                        className="text-slate-400 hover:text-rose-500">
                  <X className="w-3 h-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Téléchargement manuel */}
      <div className="mt-5 border-t border-slate-100 pt-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1">
          Téléchargement manuel — semaine au choix (lundi)
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <Input type="date" value={week} onChange={(e) => setWeek(e.target.value)}
                 className="w-40 h-9" data-testid="weekly-report-week-input" />
          <Button size="sm" variant="outline" disabled={!!downloading}
                  onClick={() => download("pdf")} data-testid="weekly-report-download-pdf">
            {downloading === "pdf" ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-1.5" />}
            Télécharger PDF
          </Button>
          <Button size="sm" variant="outline" disabled={!!downloading}
                  onClick={() => download("xlsx")} data-testid="weekly-report-download-xlsx">
            {downloading === "xlsx" ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-1.5" />}
            Télécharger XLSX
          </Button>
        </div>
        <p className="text-[10px] text-slate-500 mt-2">
          La date choisie est ramenée automatiquement au lundi de sa semaine (lundi à dimanche).
          Le téléchargement fonctionne même si l'envoi automatique est désactivé.
        </p>
      </div>
    </Card>
  );
}
