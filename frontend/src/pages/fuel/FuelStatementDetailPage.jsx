import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { STATEMENT_STATUS, fmtAmount, fmtQty } from "@/lib/fuelLabels";
import {
  ArrowLeft, RefreshCw, ClipboardCheck, Lock, Unlock, Trash2,
  FileText, FileSpreadsheet, FileDown, AlertTriangle, History,
} from "lucide-react";

const MATCH_LABEL = {
  auto_matched: "Rapprochée", matched_review: "Contrôle recommandé",
  unmatched: "À rapprocher", manual: "Attribuée manuellement",
};
const CLASS_LABEL = { professional: "Professionnel", personal: "Privé", unclassified: "Non classé" };

function Kpi({ label, value, tone = "text-slate-900", testId }) {
  return (
    <div data-testid={testId} className="bg-white rounded-lg border border-slate-200 p-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">{label}</p>
      <p className={`text-lg font-semibold mt-0.5 ${tone}`}>{value}</p>
    </div>
  );
}

function LinesTable({ lines, testId }) {
  return (
    <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
      <table className="w-full text-sm" data-testid={testId}>
        <thead>
          <tr className="border-b border-slate-200 text-left text-[10px] uppercase tracking-wider text-slate-400">
            <th className="px-3 py-2">Date utilisée</th><th className="px-3 py-2">Carte</th>
            <th className="px-3 py-2">Station</th><th className="px-3 py-2">Véhicule</th>
            <th className="px-3 py-2">Chauffeur</th><th className="px-3 py-2">Quantité</th>
            <th className="px-3 py-2">Montant CHF</th><th className="px-3 py-2">Classification</th>
            <th className="px-3 py-2">Statut</th>
          </tr>
        </thead>
        <tbody>
          {lines.length === 0 ? (
            <tr><td colSpan={9} className="px-3 py-6 text-center text-slate-400 text-xs">Aucune transaction</td></tr>
          ) : lines.map((l) => (
            <tr key={l.id} className={`border-b border-slate-100 ${l.blockers?.length ? "bg-rose-50/40" : ""}`}>
              <td className="px-3 py-2 text-xs whitespace-nowrap">
                {l.basis_date}
                <span className="block text-[9px] text-slate-400">
                  {l.basis === "accounting" ? "date comptable" : "date transaction"}
                </span>
              </td>
              <td className="px-3 py-2 text-xs font-mono">{l.card_last4 ? `•••• ${l.card_last4}` : "—"}</td>
              <td className="px-3 py-2 text-xs">{l.station_name || "—"}</td>
              <td className="px-3 py-2 text-xs">{l.vehicle_plate || <span className="text-rose-600">Non attribué</span>}</td>
              <td className="px-3 py-2 text-xs">{l.driver_name || "—"}</td>
              <td className="px-3 py-2 text-xs">{l.quantity != null ? fmtQty(l.quantity, l.unit) : "—"}</td>
              <td className="px-3 py-2 text-xs font-medium">
                {l.amount_chf != null ? fmtAmount(l.amount_chf)
                  : <span className="text-amber-600 font-semibold">En attente ({fmtAmount(l.amount_total, l.currency)})</span>}
              </td>
              <td className="px-3 py-2 text-xs">{CLASS_LABEL[l.classification] || "—"}</td>
              <td className="px-3 py-2 text-xs">
                {l.blockers?.length
                  ? <span className="text-rose-600 font-medium">{l.blockers.join(" · ")}</span>
                  : MATCH_LABEL[l.match_status] || l.match_status}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function FuelStatementDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const [stmt, setStmt] = useState(null);
  const [busy, setBusy] = useState(false);
  const [closeDlg, setCloseDlg] = useState(null);   // {blockers} | {force:true}
  const [closeReason, setCloseReason] = useState("");
  const [reopenDlg, setReopenDlg] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [reopenAck, setReopenAck] = useState(false);

  const load = useCallback(() => {
    api.get(`/livre/fuel/statements/${id}`).then(({ data }) => setStmt(data))
      .catch((e) => { toast.error(formatApiErrorDetail(e.response?.data?.detail)); navigate("/livre/carburant/decomptes"); });
  }, [id, navigate]);
  useEffect(() => { load(); }, [load]);

  async function act(fn, okMsg) {
    setBusy(true);
    try { await fn(); if (okMsg) toast.success(okMsg); load(); }
    catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function check() {
    setBusy(true);
    try {
      const { data } = await api.post(`/livre/fuel/statements/${id}/check`);
      toast[data.status === "validated" ? "success" : "warning"](
        data.status === "validated" ? "Contrôle réussi — décompte validé, prêt à clôturer"
          : `${data.blockers.total_count} élément(s) à corriger avant clôture`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function close(force = false) {
    setBusy(true);
    try {
      const { data } = await api.post(`/livre/fuel/statements/${id}/close`,
        { force, reason: force ? closeReason : null });
      toast.success(`Décompte clôturé — ${data.tx_locked} transaction(s) verrouillée(s)` +
        (data.excluded ? `, ${data.excluded} reportée(s)` : ""));
      setCloseDlg(null); setCloseReason("");
      load();
    } catch (e) {
      const d = e.response?.data?.detail;
      if (e.response?.status === 409 && d && typeof d === "object" && d.count) {
        setCloseDlg(d);
      } else toast.error(formatApiErrorDetail(d));
    } finally { setBusy(false); }
  }

  async function reopen() {
    setBusy(true);
    try {
      await api.post(`/livre/fuel/statements/${id}/reopen`, { reason: reopenReason });
      toast.success("Décompte rouvert — nouvelle version « À contrôler ». L'ancienne version est conservée.");
      setReopenDlg(false); setReopenReason(""); setReopenAck(false);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function download(fmt) {
    try {
      const { data, headers } = await api.get(
        `/livre/fuel/statements/${id}/export?fmt=${fmt}`, { responseType: "blob" });
      const match = /filename="(.+)"/.exec(headers["content-disposition"] || "");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(data);
      a.download = match ? match[1] : `decompte.${fmt === "excel" ? "xlsx" : fmt}`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast.success(`Export ${fmt.toUpperCase()} généré${stmt.status !== "closed" ? " (PROVISOIRE)" : ""}`);
    } catch { toast.error("Export impossible"); }
  }

  if (!stmt) return <p className="text-sm text-slate-400">Chargement…</p>;

  const st = STATEMENT_STATUS[stmt.status] || STATEMENT_STATUS.draft;
  const t = stmt.totals || {};
  const b = t.blockers || {};
  const period = (stmt.lines || []).filter((l) => l.section === "period");
  const carried = (stmt.lines || []).filter((l) => l.section === "carried_over");
  const editable = stmt.status !== "closed";

  return (
    <div data-testid="fuel-statement-detail-page" className="space-y-4">
      {/* En-tête */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <button data-testid="fuel-stmt-back" onClick={() => navigate("/livre/carburant/decomptes")}
                  className="text-xs text-slate-500 hover:text-slate-800 flex items-center gap-1 mb-1">
            <ArrowLeft className="w-3.5 h-3.5" /> Décomptes
          </button>
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-semibold text-slate-900 font-mono">{stmt.number}</h2>
            <span className="text-xs text-slate-400 font-semibold">V{stmt.version}</span>
            <span data-testid="fuel-stmt-status" className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${st.cls}`}>{st.label}</span>
            {stmt.type === "corrective" && (
              <span className="inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium bg-violet-100 text-violet-700 border-violet-200">Correctif</span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Période : <strong>{stmt.date_from} → {stmt.date_to}</strong> · Périmètre : flotte
            · Généré le {fmtDateTime(stmt.refreshed_at || stmt.created_at)}
            {stmt.closed_at && <> · Clôturé le {fmtDateTime(stmt.closed_at)} par {stmt.closed_by}</>}
          </p>
          {stmt.status !== "closed" && (
            <p className="text-[11px] text-amber-600 font-semibold mt-0.5">
              PROVISOIRE — ÉLÉMENTS À CONTRÔLER (les exports porteront cette mention)
            </p>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {isAdmin && editable && (
            <>
              <Button data-testid="fuel-stmt-refresh" variant="outline" size="sm" disabled={busy}
                      onClick={() => act(() => api.post(`/livre/fuel/statements/${id}/refresh`), "Décompte actualisé")}>
                <RefreshCw className="w-3.5 h-3.5 mr-1" /> Actualiser
              </Button>
              <Button data-testid="fuel-stmt-check" variant="outline" size="sm" disabled={busy} onClick={check}>
                <ClipboardCheck className="w-3.5 h-3.5 mr-1" /> Contrôler
              </Button>
              <Button data-testid="fuel-stmt-close" size="sm" disabled={busy}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      onClick={() => close(false)}>
                <Lock className="w-3.5 h-3.5 mr-1" /> Clôturer
              </Button>
              {(stmt.status === "draft" || stmt.status === "to_review") && (
                <Button data-testid="fuel-stmt-delete" variant="ghost" size="sm" disabled={busy}
                        className="text-rose-600"
                        onClick={() => window.confirm(`Supprimer le brouillon ${stmt.number} ?`)
                          && act(() => api.delete(`/livre/fuel/statements/${id}`), "Brouillon supprimé")
                          && navigate("/livre/carburant/decomptes")}>
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>
              )}
            </>
          )}
          {isAdmin && stmt.status === "closed" && (
            <Button data-testid="fuel-stmt-reopen" variant="outline" size="sm" disabled={busy}
                    className="text-amber-700 border-amber-300"
                    onClick={() => setReopenDlg(true)}>
              <Unlock className="w-3.5 h-3.5 mr-1" /> Rouvrir
            </Button>
          )}
          <Button data-testid="fuel-stmt-export-pdf" variant="outline" size="sm" onClick={() => download("pdf")}>
            <FileText className="w-3.5 h-3.5 mr-1 text-rose-600" /> PDF
          </Button>
          <Button data-testid="fuel-stmt-export-excel" variant="outline" size="sm" onClick={() => download("excel")}>
            <FileSpreadsheet className="w-3.5 h-3.5 mr-1 text-emerald-600" /> Excel
          </Button>
          <Button data-testid="fuel-stmt-export-csv" variant="outline" size="sm" onClick={() => download("csv")}>
            <FileDown className="w-3.5 h-3.5 mr-1 text-slate-500" /> CSV
          </Button>
        </div>
      </div>

      {/* Synthèse financière */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        <Kpi label="Coût total CHF" value={fmtAmount(t.amount_chf_total)} testId="fuel-stmt-kpi-total" />
        <Kpi label="Transactions" value={t.tx_count ?? 0} testId="fuel-stmt-kpi-count" />
        <Kpi label="Litres" value={fmtQty(t.liters, "L")} testId="fuel-stmt-kpi-liters" />
        <Kpi label="kWh" value={fmtQty(t.kwh, "kWh")} testId="fuel-stmt-kpi-kwh" />
        <Kpi label="Professionnel" value={fmtAmount(t.pro_chf)} tone="text-blue-700" testId="fuel-stmt-kpi-pro" />
        <Kpi label="Privé" value={fmtAmount(t.perso_chf)} tone="text-amber-700" testId="fuel-stmt-kpi-perso" />
        <Kpi label="Problèmes" value={b.total_count ?? 0}
             tone={b.total_count ? "text-rose-600" : "text-emerald-600"} testId="fuel-stmt-kpi-issues" />
      </div>

      {/* Bloc de contrôle avant clôture */}
      {b.total_count > 0 && stmt.status !== "closed" && (
        <div data-testid="fuel-stmt-blockers" className="rounded-lg border border-rose-300 bg-rose-50 p-4 space-y-2">
          <p className="text-sm font-semibold text-rose-700 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" />
            Clôture impossible — {b.total_count} élément(s) nécessitent une intervention
          </p>
          <ul className="text-xs text-rose-700 space-y-1 ml-6 list-disc">
            {b.unmatched?.count > 0 && (
              <li>
                {b.unmatched.count} transaction(s) non rapprochée(s) — {fmtAmount(b.unmatched.amount_chf)}{" "}
                <Link data-testid="fuel-stmt-link-unmatched" className="underline font-medium"
                      to="/livre/carburant/transactions?match_status=unmatched">
                  Voir les transactions non rapprochées
                </Link>
              </li>
            )}
            {b.fx_pending?.count > 0 && (
              <li>
                {b.fx_pending.count} conversion(s) en attente — montant CHF indisponible
                ({Object.entries(b.fx_pending.amounts_by_currency || {}).map(([c, v]) => `${v} ${c}`).join(", ")}){" "}
                <Link data-testid="fuel-stmt-link-fx" className="underline font-medium"
                      to="/livre/carburant/transactions?fx_status=pending">
                  Voir les conversions en attente
                </Link>
              </li>
            )}
            {b.anomalies?.count > 0 && (
              <li>
                {b.anomalies.count} anomalie(s) critique(s) non résolue(s){" "}
                <Link data-testid="fuel-stmt-link-anomalies" className="underline font-medium"
                      to="/livre/carburant/anomalies">
                  Voir les anomalies
                </Link>
              </li>
            )}
          </ul>
          {b.review?.count > 0 && (
            <p className="text-[11px] text-amber-700 ml-6">
              + {b.review.count} transaction(s) « Contrôle recommandé » (non bloquant).
            </p>
          )}
        </div>
      )}

      {stmt.close_exception?.applied && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-700">
          <strong>Exception de clôture appliquée</strong> par {stmt.close_exception.by} —{" "}
          {stmt.close_exception.excluded_count} transaction(s) reportée(s) (à intégrer à la période suivante
          ou à un décompte correctif). Motif : « {stmt.close_exception.reason} »
        </div>
      )}

      {/* Détail par véhicule / chauffeur */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {[["Par véhicule", t.by_vehicle, "fuel-stmt-by-vehicle"], ["Par chauffeur", t.by_driver, "fuel-stmt-by-driver"]].map(([title, rows, tid]) => (
          <div key={title} className="bg-white rounded-lg border border-slate-200 p-3">
            <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-2">{title}</p>
            <table className="w-full text-xs" data-testid={tid}>
              <thead>
                <tr className="text-left text-[10px] uppercase text-slate-400 border-b border-slate-200">
                  <th className="py-1.5">Libellé</th><th className="py-1.5">Tx</th>
                  <th className="py-1.5">Litres</th><th className="py-1.5">CHF</th>
                  <th className="py-1.5">Pro</th><th className="py-1.5">Privé</th>
                </tr>
              </thead>
              <tbody>
                {(rows || []).map((r) => (
                  <tr key={r.id || r.label} className="border-b border-slate-100">
                    <td className="py-1.5">{r.label}</td><td className="py-1.5">{r.tx_count}</td>
                    <td className="py-1.5">{r.liters}</td>
                    <td className="py-1.5 font-medium">{fmtAmount(r.amount_chf)}</td>
                    <td className="py-1.5">{fmtAmount(r.pro_chf)}</td>
                    <td className="py-1.5">{fmtAmount(r.perso_chf)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {/* Lignes */}
      <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">
        Transactions de la période ({period.length})
      </p>
      <LinesTable lines={period} testId="fuel-stmt-lines" />
      {carried.length > 0 && (
        <>
          <p className="text-[11px] uppercase tracking-wider text-amber-600 font-semibold">
            Transactions reportées / tardives incluses ({carried.length})
          </p>
          <LinesTable lines={carried} testId="fuel-stmt-carried" />
        </>
      )}
      {(stmt.late_transactions || []).length > 0 && (
        <>
          <p className="text-[11px] uppercase tracking-wider text-rose-600 font-semibold">
            Transactions tardives — reçues après la clôture, NON incluses ({stmt.late_transactions.length})
          </p>
          <p className="text-xs text-slate-500 -mt-2">
            Ce décompte clôturé n'est jamais modifié : intégrez-les à la période suivante ou à un décompte correctif.
          </p>
          <LinesTable lines={stmt.late_transactions} testId="fuel-stmt-late" />
        </>
      )}

      {/* Historique des versions */}
      {(stmt.versions || []).length > 0 && (
        <div className="bg-white rounded-lg border border-slate-200 p-3">
          <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold mb-2 flex items-center gap-1.5">
            <History className="w-3.5 h-3.5" /> Historique des versions
          </p>
          <table className="w-full text-xs" data-testid="fuel-stmt-versions">
            <thead>
              <tr className="text-left text-[10px] uppercase text-slate-400 border-b border-slate-200">
                <th className="py-1.5">Version</th><th className="py-1.5">Clôturée le</th>
                <th className="py-1.5">Par</th><th className="py-1.5">Total CHF</th>
                <th className="py-1.5">Écart vs suivante</th><th className="py-1.5">Statut</th>
                <th className="py-1.5">Motif de remplacement</th>
              </tr>
            </thead>
            <tbody>
              {stmt.versions.map((v) => {
                const diff = t.amount_chf_total != null && v.totals?.amount_chf_total != null
                  ? (t.amount_chf_total - v.totals.amount_chf_total).toFixed(2) : null;
                return (
                  <tr key={v.version} className="border-b border-slate-100">
                    <td className="py-1.5 font-semibold">V{v.version}</td>
                    <td className="py-1.5">{v.closed_at ? fmtDateTime(v.closed_at) : "—"}</td>
                    <td className="py-1.5">{v.closed_by}</td>
                    <td className="py-1.5">{fmtAmount(v.totals?.amount_chf_total)}</td>
                    <td className="py-1.5">{diff != null ? `${diff > 0 ? "+" : ""}${diff} CHF` : "—"}</td>
                    <td className="py-1.5"><span className="text-amber-600 font-medium">Annulée et remplacée</span></td>
                    <td className="py-1.5">{v.replace_reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Dialog exception de clôture */}
      <Dialog open={!!closeDlg} onOpenChange={(o) => !o && setCloseDlg(null)}>
        <DialogContent data-testid="fuel-stmt-force-dialog" className="max-w-md">
          <DialogHeader><DialogTitle className="text-rose-700">Clôture impossible</DialogTitle></DialogHeader>
          <div className="space-y-3 py-1 text-sm">
            <p className="text-slate-700">
              <strong>{closeDlg?.count}</strong> transaction(s) nécessitent une intervention
              ({(closeDlg?.reasons || []).join(", ")}) — montant CHF connu : {fmtAmount(closeDlg?.amount_chf)}.
            </p>
            <p className="text-xs text-slate-500">
              Corrigez-les puis relancez la clôture, ou appliquez une <strong>exception de clôture</strong> (Admin) :
              les transactions concernées seront <strong>reportées</strong> — jamais exclues silencieusement —
              et devront être intégrées à la période suivante ou à un décompte correctif.
            </p>
            <div className="space-y-1.5">
              <Label>Motif de l'exception (obligatoire, audité)</Label>
              <Input data-testid="fuel-stmt-force-reason" value={closeReason}
                     onChange={(e) => setCloseReason(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCloseDlg(null)}>Corriger d'abord</Button>
            <Button data-testid="fuel-stmt-force-confirm" disabled={busy || !closeReason.trim()}
                    className="bg-amber-600 hover:bg-amber-700 text-white"
                    onClick={() => close(true)}>
              Clôturer avec exception
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog réouverture */}
      <Dialog open={reopenDlg} onOpenChange={(o) => { if (!o) { setReopenDlg(false); setReopenAck(false); } }}>
        <DialogContent data-testid="fuel-stmt-reopen-dialog" className="max-w-md">
          <DialogHeader><DialogTitle className="text-amber-700">Rouvrir le décompte clôturé</DialogTitle></DialogHeader>
          <div className="space-y-3 py-1">
            <p className="text-xs text-slate-600">
              La version <strong>V{stmt.version}</strong> sera archivée « Annulée et remplacée » (jamais supprimée)
              et le décompte repassera en <strong>À contrôler</strong> en version V{stmt.version + 1}.
              Les transactions seront déverrouillées jusqu'à la prochaine clôture.
              Pour la comptabilité, un <strong>décompte correctif</strong> est souvent préférable.
            </p>
            <label className="flex items-start gap-2 text-xs text-slate-700">
              <Checkbox data-testid="fuel-stmt-reopen-ack" checked={reopenAck} onCheckedChange={setReopenAck} />
              Je comprends que cette action est exceptionnelle, auditée, et qu'une nouvelle clôture sera requise.
            </label>
            <div className="space-y-1.5">
              <Label>Motif (obligatoire)</Label>
              <Input data-testid="fuel-stmt-reopen-reason" value={reopenReason}
                     onChange={(e) => setReopenReason(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReopenDlg(false)}>Annuler</Button>
            <Button data-testid="fuel-stmt-reopen-confirm" disabled={busy || !reopenAck || !reopenReason.trim()}
                    className="bg-amber-600 hover:bg-amber-700 text-white" onClick={reopen}>
              Rouvrir (V{stmt.version + 1})
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
