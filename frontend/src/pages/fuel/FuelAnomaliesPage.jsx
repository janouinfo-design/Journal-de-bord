import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import SubTabs from "@/components/layout/SubTabs";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { ANOMALY_TYPE_LABEL, ANOMALY_SEVERITY, ANOMALY_STATUS, fmtAmount } from "@/lib/fuelLabels";
import TxDetailDialog from "@/components/fuel/TxDetailDialog";
import { ScanSearch, CheckCircle2, Wrench, XCircle } from "lucide-react";

const DECISIONS = [
  { action: "justify", label: "Justifier", icon: CheckCircle2, hint: "L'écart est expliqué (ex. jerrican rempli en plus)" },
  { action: "correct", label: "Marquer corrigée", icon: Wrench, hint: "La donnée source a été corrigée" },
  { action: "reject", label: "Rejeter", icon: XCircle, hint: "Fausse alerte" },
];

export default function FuelAnomaliesPage() {
  const { user } = useAuth();
  const canAct = ["admin", "superadmin", "manager"].includes(user?.role);
  const [status, setStatus] = useState("open");
  const [data, setData] = useState({ items: [], counts_by_status: {} });
  const [scanning, setScanning] = useState(false);
  const [decideDlg, setDecideDlg] = useState(null); // {anomaly, action}
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [detailTxId, setDetailTxId] = useState(null);

  const load = useCallback(() => {
    api.get("/livre/fuel/anomalies", { params: { status } })
      .then(({ data }) => setData(data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, [status]);
  useEffect(() => { load(); }, [load]);

  async function scan() {
    setScanning(true);
    try {
      const { data: r } = await api.post("/livre/fuel/anomalies/scan");
      toast.success(`Analyse terminée : ${r.created} nouvelle(s) alerte(s) — ${r.open_total} ouverte(s) au total`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setScanning(false); }
  }

  async function decide() {
    setBusy(true);
    try {
      await api.post(`/livre/fuel/anomalies/${decideDlg.anomaly.id}/decide`,
        { action: decideDlg.action, reason });
      toast.success("Décision enregistrée et auditée");
      setDecideDlg(null); setReason("");
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  const counts = data.counts_by_status || {};
  const tabs = Object.entries(ANOMALY_STATUS).map(([value, s]) => ({
    value, label: `${s.label} (${counts[value] || 0})`, testId: `fuel-anomaly-tab-${value}`,
  }));

  return (
    <div data-testid="fuel-anomalies-page" className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-slate-500 max-w-2xl">
          Détection automatique après chaque import, saisie ou rapprochement, selon les seuils
          configurés dans les Paramètres. Chaque alerte explique précisément l'écart constaté ;
          toute décision exige un motif et est auditée.
        </p>
        {canAct && (
          <Button data-testid="fuel-anomaly-scan-btn" onClick={scan} disabled={scanning}
                  className="bg-[#2196F3] hover:bg-[#1976D2] text-white h-9 shrink-0">
            <ScanSearch className="w-4 h-4 mr-1.5" />
            {scanning ? "Analyse…" : "Analyser maintenant"}
          </Button>
        )}
      </div>

      <SubTabs tabs={tabs} current={status} onChange={setStatus} />

      <div className="space-y-2">
        {data.items.length === 0 ? (
          <div className="bg-white rounded-lg border border-slate-200 p-8 text-center text-sm text-slate-400">
            Aucune anomalie {ANOMALY_STATUS[status]?.label.toLowerCase()}
          </div>
        ) : data.items.map((a) => {
          const sev = ANOMALY_SEVERITY[a.severity] || ANOMALY_SEVERITY.warning;
          const tx = a.transaction || {};
          return (
            <div key={a.id} data-testid={`fuel-anomaly-${a.id}`}
                 className="bg-white rounded-lg border border-slate-200 p-3.5 flex flex-wrap items-start gap-3">
              <div className="flex flex-col gap-1 shrink-0 w-40">
                <span className={`inline-flex w-fit px-2 py-0.5 rounded-full border text-[11px] font-semibold ${sev.cls}`}>
                  {sev.label}
                </span>
                <span className="text-xs font-medium text-slate-700">{ANOMALY_TYPE_LABEL[a.type] || a.type}</span>
                <span className="text-[10px] text-slate-400">{fmtDateTime(a.detected_at)}</span>
              </div>
              <div className="flex-1 min-w-[260px]">
                <p data-testid={`fuel-anomaly-explanation-${a.id}`} className="text-sm text-slate-800">{a.explanation}</p>
                <button type="button" data-testid={`fuel-anomaly-tx-link-${a.id}`}
                        onClick={() => setDetailTxId(a.transaction_id)}
                        className="text-xs text-[#2196F3] hover:underline mt-1">
                  {fmtDateTime(tx.tx_datetime)} · {tx.station_name || "station inconnue"} ·{" "}
                  {tx.amount_total != null ? fmtAmount(tx.amount_total, tx.currency) : "—"}
                  {tx.vehicle_plate ? ` · ${tx.vehicle_plate}` : ""}
                  {tx.card_last4 ? ` · •••• ${tx.card_last4}` : ""}
                </button>
                {a.related_transaction_id && (
                  <button type="button" data-testid={`fuel-anomaly-related-link-${a.id}`}
                          onClick={() => setDetailTxId(a.related_transaction_id)}
                          className="block text-xs text-slate-500 hover:underline">
                    Voir la transaction liée →
                  </button>
                )}
                {a.status !== "open" && (
                  <p className="text-xs text-slate-500 mt-1">
                    <span className={`inline-flex px-1.5 py-0.5 rounded border text-[10px] font-medium mr-1.5 ${ANOMALY_STATUS[a.status].cls}`}>
                      {ANOMALY_STATUS[a.status].label}
                    </span>
                    par {a.decided_by} le {fmtDateTime(a.decided_at)} — « {a.decision_reason} »
                  </p>
                )}
              </div>
              {canAct && a.status === "open" && (
                <div className="flex flex-col gap-1.5 shrink-0">
                  {DECISIONS.map((d) => (
                    <Button key={d.action} data-testid={`fuel-anomaly-${d.action}-${a.id}`}
                            variant="outline" size="sm" className="h-7 text-xs justify-start"
                            title={d.hint}
                            onClick={() => { setDecideDlg({ anomaly: a, action: d.action }); setReason(""); }}>
                      <d.icon className="w-3.5 h-3.5 mr-1.5" /> {d.label}
                    </Button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <Dialog open={!!decideDlg} onOpenChange={(o) => !o && setDecideDlg(null)}>
        <DialogContent data-testid="fuel-anomaly-decide-dialog" className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {DECISIONS.find((d) => d.action === decideDlg?.action)?.label} l'anomalie
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-2 py-1">
            <p className="text-xs text-slate-500">{decideDlg?.anomaly?.explanation}</p>
            <div className="space-y-1.5">
              <Label>Motif (obligatoire, audité)</Label>
              <Input data-testid="fuel-anomaly-decide-reason" value={reason}
                     onChange={(e) => setReason(e.target.value)}
                     placeholder={DECISIONS.find((d) => d.action === decideDlg?.action)?.hint} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDecideDlg(null)}>Annuler</Button>
            <Button data-testid="fuel-anomaly-decide-confirm" disabled={busy || !reason.trim()} onClick={decide}>
              Confirmer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {detailTxId && <TxDetailDialog txId={detailTxId} onClose={() => setDetailTxId(null)} onChanged={load} />}
    </div>
  );
}
