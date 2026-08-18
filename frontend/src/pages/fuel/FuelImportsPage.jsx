import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ROW_STATUS, fmtAmount } from "@/lib/fuelLabels";
import { Upload, FileSpreadsheet, ArrowRight, CheckCircle2, Eye } from "lucide-react";

const JOB_STATUS = {
  mapping: { label: "Mapping à définir", cls: "bg-sky-100 text-sky-700" },
  preview: { label: "Aperçu prêt", cls: "bg-amber-100 text-amber-700" },
  confirmed: { label: "Importé", cls: "bg-emerald-100 text-emerald-700" },
};

export default function FuelImportsPage() {
  const [jobs, setJobs] = useState([]);
  const [providers, setProviders] = useState([]);
  const [provider, setProvider] = useState("Autre");
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  // wizard: {job_id, columns, mapping, fields, sample, counts, step: mapping|preview|done}
  const [wiz, setWiz] = useState(null);
  const [rows, setRows] = useState({ items: [], total: 0 });
  const [rowFilter, setRowFilter] = useState("");
  const [saveDefault, setSaveDefault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [forceRow, setForceRow] = useState(null);  // {row, reason}

  const loadJobs = useCallback(() => {
    api.get("/livre/fuel/imports").then(({ data }) => setJobs(data)).catch(() => {});
  }, []);
  useEffect(() => {
    loadJobs();
    api.get("/livre/fuel/refs").then(({ data }) => setProviders(data.providers || [])).catch(() => {});
  }, [loadJobs]);

  async function upload(file) {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("provider", provider);
    setUploading(true);
    try {
      const { data } = await api.post("/livre/fuel/imports", fd,
        { headers: { "Content-Type": "multipart/form-data" } });
      setWiz({
        job_id: data.job_id, columns: data.columns, fields: data.fields,
        sample: data.sample, total: data.total, step: "mapping",
        mapping: Object.fromEntries(data.columns.map((c) => [c, data.guessed_mapping?.[c] || "ignore"])),
        counts: null,
      });
      loadJobs();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function applyMapping() {
    setBusy(true);
    try {
      const { data } = await api.post(`/livre/fuel/imports/${wiz.job_id}/mapping`,
        { mapping: wiz.mapping, save_as_default: saveDefault });
      setWiz({ ...wiz, step: "preview", counts: data.counts });
      setRowFilter("");
      await loadRows(wiz.job_id, "");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function loadRows(jobId, status) {
    const params = { page_size: 200 };
    if (status) params.status = status;
    const { data } = await api.get(`/livre/fuel/imports/${jobId}/rows`, { params });
    setRows(data);
  }

  async function confirm() {
    setBusy(true);
    try {
      const { data } = await api.post(`/livre/fuel/imports/${wiz.job_id}/confirm`);
      toast.success(
        `${data.imported} transaction(s) importée(s) — ` +
        `${data.match?.auto_matched || 0} rapprochées auto, ${data.duplicates_in_review} doublon(s) en révision, ` +
        `${data.invalid_skipped} invalide(s) ignorée(s)`);
      setWiz({ ...wiz, step: "done", result: data });
      loadJobs();
      await loadRows(wiz.job_id, "");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function doForceRow() {
    setBusy(true);
    try {
      await api.post(`/livre/fuel/imports/${forceRow.jobId}/rows/${forceRow.row.id}/force`,
        { reason: forceRow.reason });
      toast.success("Ligne importée malgré le doublon (motif enregistré)");
      setForceRow(null);
      await loadRows(forceRow.jobId, rowFilter);
      loadJobs();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function openJob(job) {
    setWiz({ job_id: job.id, step: "review", counts: job.counts, jobDoc: job });
    setRowFilter("");
    await loadRows(job.id, "");
  }

  const mappedFields = wiz ? Object.values(wiz.mapping || {}) : [];
  const mappingValid = mappedFields.includes("tx_datetime") && mappedFields.includes("amount_total");

  return (
    <div data-testid="fuel-imports-page" className="space-y-4">
      {/* Upload */}
      <div className="bg-white rounded-lg border border-slate-200 p-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label>Fournisseur du relevé</Label>
          <Select value={provider} onValueChange={setProvider}>
            <SelectTrigger data-testid="fuel-import-provider" className="w-44 h-9"><SelectValue /></SelectTrigger>
            <SelectContent>
              {providers.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Fichier CSV ou XLSX</Label>
          <Input data-testid="fuel-import-file" ref={fileRef} type="file" accept=".csv,.xlsx,.xls"
                 className="h-9 w-72" onChange={(e) => upload(e.target.files?.[0])} disabled={uploading} />
        </div>
        <p className="text-xs text-slate-400 flex items-center gap-1.5 pb-2">
          <Upload className="w-3.5 h-3.5" />
          {uploading ? "Analyse du fichier…" : "L'assistant détecte les colonnes puis vous validez le mapping."}
        </p>
      </div>

      {/* Étape mapping */}
      {wiz?.step === "mapping" && (
        <div data-testid="fuel-import-mapping-step" className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
          <p className="text-sm font-semibold text-slate-800 flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4" /> Étape 1 — Associer les colonnes ({wiz.total} lignes détectées)
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {wiz.columns.map((col) => (
              <div key={col} className="flex items-center gap-2">
                <div className="w-1/2">
                  <p className="text-xs font-medium text-slate-700 truncate">{col}</p>
                  <p className="text-[10px] text-slate-400 truncate">
                    ex : {(wiz.sample || []).slice(0, 2).map((r) => r[col]).filter(Boolean).join(" · ") || "—"}
                  </p>
                </div>
                <Select value={wiz.mapping[col] || "ignore"}
                        onValueChange={(v) => setWiz({ ...wiz, mapping: { ...wiz.mapping, [col]: v } })}>
                  <SelectTrigger data-testid={`fuel-import-map-${col}`} className="h-8 flex-1 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ignore">— Ignorer —</SelectItem>
                    {wiz.fields.map((f) => <SelectItem key={f.key} value={f.key}>{f.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>
          {!mappingValid && (
            <p className="text-xs text-amber-600">
              Le mapping doit inclure au minimum « Date et heure de la transaction » et « Montant TTC ».
            </p>
          )}
          <div className="flex items-center justify-between pt-1">
            <label className="flex items-center gap-2 text-xs text-slate-600">
              <Checkbox data-testid="fuel-import-save-default" checked={saveDefault} onCheckedChange={setSaveDefault} />
              Mémoriser ce mapping pour « {provider} »
            </label>
            <Button data-testid="fuel-import-apply-mapping" onClick={applyMapping} disabled={busy || !mappingValid}>
              {busy ? "Analyse…" : <>Analyser les lignes <ArrowRight className="w-4 h-4 ml-1.5" /></>}
            </Button>
          </div>
        </div>
      )}

      {/* Étape aperçu / révision */}
      {wiz && wiz.step !== "mapping" && (
        <div data-testid="fuel-import-preview-step" className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
          <p className="text-sm font-semibold text-slate-800">
            {wiz.step === "preview" ? "Étape 2 — Aperçu avant import" :
             wiz.step === "done" ? "Import terminé — file de vérification" : "Détail de l'import"}
          </p>
          {wiz.counts && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(wiz.counts).filter(([k]) => k !== "total").map(([k, v]) => {
                const rs = ROW_STATUS[k];
                return (
                  <button key={k} type="button" data-testid={`fuel-import-count-${k}`}
                          onClick={() => { const nf = rowFilter === k ? "" : k; setRowFilter(nf); loadRows(wiz.job_id, nf); }}
                          className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors ${rs ? rs.cls : "bg-slate-100 text-slate-600"} ${rowFilter === k ? "ring-2 ring-slate-400" : ""}`}>
                    {(rs || {}).label || k} : {v}
                  </button>
                );
              })}
              <span className="px-2.5 py-1 text-[11px] text-slate-400">Total : {wiz.counts.total}</span>
            </div>
          )}
          <div className="rounded-md border border-slate-200 overflow-x-auto max-h-80 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-slate-200 text-left text-[10px] uppercase tracking-wider text-slate-400">
                  <th className="px-3 py-2">#</th><th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Carte</th><th className="px-3 py-2">Station</th>
                  <th className="px-3 py-2">Montant</th><th className="px-3 py-2">Statut</th>
                  <th className="px-3 py-2">Erreurs</th><th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {rows.items.map((r) => {
                  const rs = ROW_STATUS[r.status] || ROW_STATUS.pending;
                  const n = r.normalized || {};
                  const forceable = !r.imported && ["duplicate", "unknown_card", "amount_mismatch"].includes(r.status);
                  return (
                    <tr key={r.id} data-testid={`fuel-import-row-${r.row_index}`} className="border-b border-slate-100">
                      <td className="px-3 py-1.5 text-slate-400">{r.row_index + 1}</td>
                      <td className="px-3 py-1.5 whitespace-nowrap">{n.tx_datetime ? fmtDateTime(n.tx_datetime) : "—"}</td>
                      <td className="px-3 py-1.5 font-mono">{n.card_last4 ? `•••• ${n.card_last4}` : "—"}</td>
                      <td className="px-3 py-1.5">{n.station_name || "—"}</td>
                      <td className="px-3 py-1.5">{n.amount_total != null ? fmtAmount(n.amount_total, n.currency) : "—"}</td>
                      <td className="px-3 py-1.5">
                        <span className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium ${rs.cls}`}>
                          {r.imported ? "Importée" : rs.label}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-rose-600">{(r.errors || []).join(" ; ")}</td>
                      <td className="px-3 py-1.5">
                        {forceable && wiz.step !== "preview" && (
                          <Button data-testid={`fuel-import-force-${r.row_index}`} variant="outline" size="sm"
                                  className="h-6 text-[10px]"
                                  onClick={() => setForceRow({ jobId: wiz.job_id, row: r, reason: "" })}>
                            Importer quand même
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between">
            <Button variant="outline" onClick={() => setWiz(null)}>Fermer</Button>
            {wiz.step === "preview" && (
              <Button data-testid="fuel-import-confirm" onClick={confirm} disabled={busy}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white">
                <CheckCircle2 className="w-4 h-4 mr-1.5" />
                {busy ? "Import…" : "Confirmer l'import"}
              </Button>
            )}
          </div>
          {wiz.step === "preview" && (
            <p className="text-[11px] text-slate-400">
              Les lignes valides, « carte inconnue » et « montant incohérent » seront importées.
              Les doublons probables restent en file de vérification (importables ensuite avec motif) ;
              les lignes invalides sont ignorées.
            </p>
          )}
        </div>
      )}

      {/* Historique des imports */}
      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <p className="px-4 pt-4 text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Historique des imports</p>
        <table className="w-full text-sm mt-2">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-2">Date</th><th className="px-4 py-2">Fichier</th>
              <th className="px-4 py-2">Fournisseur</th><th className="px-4 py-2">Lignes</th>
              <th className="px-4 py-2">Importées</th><th className="px-4 py-2">Statut</th><th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-6 text-center text-slate-400">Aucun import</td></tr>
            ) : jobs.map((j) => {
              const js = JOB_STATUS[j.status] || { label: j.status, cls: "bg-slate-100 text-slate-500" };
              return (
                <tr key={j.id} data-testid={`fuel-import-job-${j.id}`} className="border-b border-slate-100">
                  <td className="px-4 py-2 text-xs whitespace-nowrap">{fmtDateTime(j.created_at)}</td>
                  <td className="px-4 py-2 text-xs">{j.filename}</td>
                  <td className="px-4 py-2 text-xs">{j.provider}</td>
                  <td className="px-4 py-2 text-xs">{j.counts?.total ?? "—"}</td>
                  <td className="px-4 py-2 text-xs">{j.imported_count ?? "—"}</td>
                  <td className="px-4 py-2">
                    <span className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-medium ${js.cls}`}>{js.label}</span>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button data-testid={`fuel-import-open-${j.id}`} variant="ghost" size="sm"
                            title="Voir les lignes" onClick={() => openJob(j)}>
                      <Eye className="w-4 h-4" />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Dialog force */}
      <Dialog open={!!forceRow} onOpenChange={(o) => !o && setForceRow(null)}>
        <DialogContent data-testid="fuel-import-force-dialog" className="max-w-md">
          <DialogHeader><DialogTitle>Importer malgré le doublon probable</DialogTitle></DialogHeader>
          <div className="space-y-2 py-1">
            <p className="text-xs text-slate-500">
              Cette ligne ressemble à une transaction déjà importée. Indiquez pourquoi il s'agit
              bien d'une transaction distincte.
            </p>
            <Input data-testid="fuel-import-force-reason" placeholder="Motif (obligatoire)"
                   value={forceRow?.reason || ""}
                   onChange={(e) => setForceRow({ ...forceRow, reason: e.target.value })} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setForceRow(null)}>Annuler</Button>
            <Button data-testid="fuel-import-force-confirm" onClick={doForceRow}
                    disabled={busy || !forceRow?.reason?.trim()}
                    className="bg-amber-600 hover:bg-amber-700 text-white">Importer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
