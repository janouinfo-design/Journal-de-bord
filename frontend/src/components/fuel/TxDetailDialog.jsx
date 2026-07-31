import { useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { MATCH_STATUS, PRODUCT_LABEL, SOURCE_LABEL, fmtAmount, fmtQty } from "@/lib/fuelLabels";
import { Download, Paperclip, AlertTriangle, GitMerge } from "lucide-react";

function Row({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1 text-sm">
      <span className="text-slate-400 text-xs shrink-0">{label}</span>
      <span className="text-slate-800 text-xs text-right">{children ?? "—"}</span>
    </div>
  );
}

export default function TxDetailDialog({ txId, onClose, onChanged }) {
  const { user } = useAuth();
  const role = user?.role;
  const canMatch = role === "admin" || role === "manager" || role === "superadmin";
  const canWrite = canMatch || role === "driver";
  const [tx, setTx] = useState(null);
  const [refs, setRefs] = useState({ vehicles: [], drivers: [] });
  const [matchForm, setMatchForm] = useState({ vehicle_id: "", driver_id: "", reason: "" });
  const [issueMsg, setIssueMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!txId) return;
    api.get(`/livre/fuel/transactions/${txId}`)
      .then(({ data }) => {
        setTx(data);
        setMatchForm({ vehicle_id: data.vehicle_id || "", driver_id: data.driver_id || "", reason: "" });
      })
      .catch((e) => { toast.error(formatApiErrorDetail(e.response?.data?.detail)); onClose(); });
    if (canMatch) {
      api.get("/livre/fuel/refs").then(({ data }) => setRefs(data)).catch(() => {});
    }
  }, [txId, onClose, canMatch]);

  async function reload() {
    const { data } = await api.get(`/livre/fuel/transactions/${txId}`);
    setTx(data);
    onChanged?.();
  }

  async function saveMatch() {
    setBusy(true);
    try {
      await api.patch(`/livre/fuel/transactions/${txId}/match`, {
        vehicle_id: matchForm.vehicle_id || null,
        driver_id: matchForm.driver_id || null,
        reason: matchForm.reason,
      });
      toast.success("Attribution manuelle enregistrée");
      await reload();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function reportIssue() {
    setBusy(true);
    try {
      await api.post(`/livre/fuel/transactions/${txId}/report-issue`, { message: issueMsg });
      toast.success("Erreur signalée — un gestionnaire sera notifié");
      setIssueMsg("");
      await reload();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function uploadDoc(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    setBusy(true);
    try {
      await api.post(`/livre/fuel/transactions/${txId}/documents`, fd,
        { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Justificatif ajouté");
      await reload();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function downloadDoc(doc) {
    try {
      const { data } = await api.get(
        `/livre/fuel/transactions/${txId}/documents/${doc.id}/download`, { responseType: "blob" });
      const href = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = href; a.download = doc.filename; a.click();
      URL.revokeObjectURL(href);
    } catch { toast.error("Téléchargement impossible"); }
  }

  const s = tx ? (MATCH_STATUS[tx.match_status] || MATCH_STATUS.unmatched) : null;
  const md = tx?.match_detail;

  return (
    <Dialog open={!!txId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="fuel-tx-detail-dialog" className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Transaction {tx ? fmtDateTime(tx.tx_datetime) : "…"}
            {s && <span className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${s.cls}`}>{s.label}</span>}
          </DialogTitle>
        </DialogHeader>
        {!tx ? <p className="text-sm text-slate-400">Chargement…</p> : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 rounded-md border border-slate-200 p-3">
              <Row label="Carte">{tx.card_last4 ? `•••• ${tx.card_last4}` : "—"} {tx.provider ? `(${tx.provider})` : ""}</Row>
              <Row label="Source">{SOURCE_LABEL[tx.source] || tx.source}</Row>
              <Row label="Station">{tx.station_name}</Row>
              <Row label="Pays">{tx.country}</Row>
              <Row label="Produit">{PRODUCT_LABEL[tx.product_type] || tx.product_type || "—"}</Row>
              <Row label="Quantité">{tx.quantity != null ? fmtQty(tx.quantity, tx.unit) : "—"}</Row>
              <Row label="Prix unitaire">{tx.unit_price != null ? fmtAmount(tx.unit_price, tx.currency) : "—"}</Row>
              <Row label="Montant TTC"><strong data-testid="fuel-tx-detail-amount">{fmtAmount(tx.amount_total, tx.currency)}</strong></Row>
              <Row label="TVA">{tx.vat_amount != null ? fmtAmount(tx.vat_amount, tx.currency) : "—"}</Row>
              <Row label="Kilométrage">{tx.mileage != null ? `${tx.mileage} km` : "—"}</Row>
              <Row label="Véhicule">{tx.vehicle_plate || (tx.vehicle_hint ? `${tx.vehicle_hint} (relevé)` : "—")}</Row>
              <Row label="Chauffeur">{tx.driver_name}</Row>
              {tx.invoice_ref && <Row label="Facture / relevé">{tx.invoice_ref}</Row>}
              {tx.comment && <Row label="Commentaire">{tx.comment}</Row>}
              {tx.manual_reason && <Row label="Motif saisie manuelle">{tx.manual_reason}</Row>}
              {tx.forced_import_reason && <Row label="Import forcé — motif">{tx.forced_import_reason}</Row>}
            </div>

            {/* Score explicable */}
            <div className="rounded-md border border-slate-200 p-3">
              <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-2 flex items-center gap-1.5">
                <GitMerge className="w-3.5 h-3.5" /> Rapprochement
                {md?.score != null && (
                  <span data-testid="fuel-tx-detail-score" className="ml-auto text-slate-800 normal-case tracking-normal">
                    Score : <strong>{md.score}/100</strong>
                  </span>
                )}
              </p>
              {md?.status === "manual" ? (
                <p className="text-xs text-sky-700">
                  Attribué manuellement par {md.decided_by} — motif : « {md.reason} »
                </p>
              ) : (md?.breakdown || []).length ? (
                <ul className="space-y-1">
                  {md.breakdown.map((b, i) => (
                    <li key={`${b.rule}-${i}`} className="flex items-center justify-between text-xs">
                      <span className="text-slate-600">{b.label}</span>
                      <span className={b.points >= 0 ? "text-emerald-600 font-medium" : "text-rose-600 font-medium"}>
                        {b.points >= 0 ? "+" : ""}{b.points}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-slate-400">Aucun élément de rapprochement — transaction non rattachée.</p>
              )}
            </div>

            {/* Attribution manuelle — admin/manager uniquement */}
            {canMatch && (
              <div className="rounded-md border border-slate-200 p-3 space-y-2">
                <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Attribution manuelle</p>
                <div className="grid grid-cols-2 gap-2">
                  <Select value={matchForm.vehicle_id || "none"}
                          onValueChange={(v) => setMatchForm({ ...matchForm, vehicle_id: v === "none" ? "" : v })}>
                    <SelectTrigger data-testid="fuel-tx-match-vehicle"><SelectValue placeholder="Véhicule" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Aucun véhicule</SelectItem>
                      {refs.vehicles.map((v) => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Select value={matchForm.driver_id || "none"}
                          onValueChange={(v) => setMatchForm({ ...matchForm, driver_id: v === "none" ? "" : v })}>
                    <SelectTrigger data-testid="fuel-tx-match-driver"><SelectValue placeholder="Chauffeur" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Aucun chauffeur</SelectItem>
                      {refs.drivers.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex gap-2">
                  <Input data-testid="fuel-tx-match-reason" placeholder="Motif (obligatoire)"
                         value={matchForm.reason}
                         onChange={(e) => setMatchForm({ ...matchForm, reason: e.target.value })} />
                  <Button data-testid="fuel-tx-match-save" onClick={saveMatch}
                          disabled={busy || !matchForm.reason.trim()}>Attribuer</Button>
                </div>
              </div>
            )}

            {/* Justificatifs */}
            <div className="rounded-md border border-slate-200 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold flex items-center gap-1.5">
                  <Paperclip className="w-3.5 h-3.5" /> Justificatifs
                </p>
                {canWrite && (
                  <label className="text-xs text-[#2196F3] cursor-pointer hover:underline" data-testid="fuel-tx-doc-upload-label">
                    Ajouter un justificatif
                    <input type="file" data-testid="fuel-tx-doc-upload" className="hidden"
                           accept=".pdf,.jpg,.jpeg,.png,.webp,.heic"
                           onChange={(e) => { uploadDoc(e.target.files?.[0]); e.target.value = ""; }} />
                  </label>
                )}
              </div>
              {(tx.documents || []).length === 0 ? (
                <p className="text-xs text-slate-400">Aucun justificatif</p>
              ) : tx.documents.map((d) => (
                <div key={d.id} className="flex items-center justify-between text-xs">
                  <span className="text-slate-700 truncate">{d.filename}
                    <span className="text-slate-400 ml-1">({Math.round(d.size_bytes / 1024)} Ko)</span>
                  </span>
                  <Button data-testid={`fuel-tx-doc-download-${d.id}`} variant="ghost" size="sm" onClick={() => downloadDoc(d)}>
                    <Download className="w-3.5 h-3.5" />
                  </Button>
                </div>
              ))}
            </div>

            {/* Signaler une erreur */}
            {canWrite && (
              <div className="rounded-md border border-amber-200 bg-amber-50/50 p-3 space-y-2">
                <p className="text-[11px] uppercase tracking-wider text-amber-600 font-semibold flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" /> Signaler une erreur
                </p>
                {(tx.issues || []).map((i) => (
                  <p key={i.id} className="text-xs text-amber-700">
                    « {i.message} » — {i.reported_by}, {fmtDateTime(i.reported_at)}
                  </p>
                ))}
                <div className="flex gap-2">
                  <Input data-testid="fuel-tx-issue-input" placeholder="Décrivez le problème (montant, station, véhicule…)"
                         value={issueMsg} onChange={(e) => setIssueMsg(e.target.value)} />
                  <Button data-testid="fuel-tx-issue-send" variant="outline" onClick={reportIssue}
                          disabled={busy || !issueMsg.trim()}>Signaler</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
