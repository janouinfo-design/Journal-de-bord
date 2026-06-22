/* Modal form to create or edit a fine.
 *
 * Used from FinesPage. Keeps every field of the data model but groups them
 * into 5 collapsible sections to stay scannable on tablet/mobile.
 */
import { useEffect, useMemo, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Loader2, Sparkles, Map, ScanLine, Upload, Download, Trash2, FileText, Image as ImageIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useRef } from "react";
import {
  FINE_STATUSES, INFRACTION_TYPES, PRIORITIES,
} from "@/constants/fines";

const SECTION_CLS = "border border-slate-200 rounded-md bg-slate-50/30";
const SECTION_HEAD = "px-3 py-2 text-[10px] uppercase tracking-[0.14em] font-semibold text-slate-500 border-b border-slate-200";
const SECTION_BODY = "p-3 grid grid-cols-1 sm:grid-cols-2 gap-3";

const BLANK = {
  ref_fine: "", authority: "", country: "CH", canton: "", city: "",
  received_at: "", infraction_at: "", location: "",
  vehicle_id: "", driver_id: "",
  infraction_type: "other", infraction_details: "",
  amount: 0, admin_fees: 0, currency: "CHF",
  due_date: "", paid_at: "",
  status: "received", priority: "normal",
  case_owner: "", internal_notes: "",
};

/** Convert an ISO datetime string to a value compatible with <input type="datetime-local"> */
function isoToLocal(s) {
  if (!s) return "";
  try {
    const d = new Date(s);
    // Adjust for local timezone offset so the displayed time matches what the user stored
    const off = d.getTimezoneOffset() * 60000;
    return new Date(d - off).toISOString().slice(0, 16);
  } catch { return ""; }
}

function isoToDate(s) {
  if (!s) return "";
  try { return new Date(s).toISOString().slice(0, 10); } catch { return ""; }
}

export default function FineFormDialog({ open, onOpenChange, fineId, meta, onSaved }) {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [form, setForm] = useState(BLANK);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [identifying, setIdentifying] = useState(false);
  const [scanning, setScanning] = useState(false);
  const isEdit = !!fineId;

  useEffect(() => {
    if (!open) return;
    if (!fineId) { setForm(BLANK); return; }
    setLoading(true);
    api.get(`/livre/fines/${fineId}`)
      .then(({ data }) => setForm({
        ...BLANK, ...data,
        received_at: isoToDate(data.received_at),
        due_date: isoToDate(data.due_date),
        paid_at: isoToDate(data.paid_at),
        infraction_at: isoToLocal(data.infraction_at),
      }))
      .catch(e => toast.error(formatApiErrorDetail(e?.response?.data?.detail)))
      .finally(() => setLoading(false));
  }, [open, fineId]);

  function set(field, value) { setForm(f => ({ ...f, [field]: value })); }

  async function reloadDocs() {
    if (!fineId) return;
    try {
      const { data } = await api.get(`/livre/fines/${fineId}`);
      setForm(f => ({ ...f, documents: data.documents || [] }));
    } catch (e) { /* silent */ }
  }

  async function uploadDoc(file, kind) {
    if (!fineId || !file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    try {
      await api.post(`/livre/fines/${fineId}/documents`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`${file.name} ajouté`);
      reloadDocs();
      onSaved?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Upload refusé");
    }
  }

  async function deleteDoc(doc) {
    if (!window.confirm(`Supprimer le document « ${doc.filename} » ?`)) return;
    try {
      await api.delete(`/livre/fines/${fineId}/documents/${doc.id}`);
      toast.success("Document supprimé");
      reloadDocs();
      onSaved?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail));
    }
  }

  function downloadDoc(doc) {
    // Use the api client so the Authorization header is included
    api.get(`/livre/fines/${fineId}/documents/${doc.id}/download`, { responseType: "blob" })
      .then((res) => {
        const url = URL.createObjectURL(res.data);
        const a = document.createElement("a");
        a.href = url;
        a.download = doc.filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      })
      .catch((e) => toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Téléchargement refusé"));
  }

  const total = useMemo(
    () => (Number(form.amount) || 0) + (Number(form.admin_fees) || 0),
    [form.amount, form.admin_fees],
  );

  async function runIdentify() {
    if (!isEdit) {
      toast.info("Enregistrez d'abord l'amende pour lancer l'identification.");
      return;
    }
    if (!form.vehicle_id || !form.infraction_at) {
      toast.error("Véhicule et date/heure de l'infraction requis.");
      return;
    }
    setIdentifying(true);
    try {
      const { data } = await api.post(`/livre/fines/${fineId}/identify-driver`);
      const result = data.result || {};
      if (result.driver_id) {
        setForm(f => ({
          ...f,
          driver_id: result.driver_id,
          driver_name: result.driver_name,
          driver_confidence: result.confidence,
          driver_sources: result.sources,
          driver_validated_manually: false,
        }));
        toast.success(`Chauffeur identifié : ${result.driver_name} (${result.confidence}%)`);
      } else {
        toast.warning("Aucun chauffeur identifié par croisement BLE/GPS/affectation.");
      }
      onSaved?.();
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail));
    } finally { setIdentifying(false); }
  }

  function openTrip() {
    if (!form.vehicle_id || !form.infraction_at) {
      toast.error("Véhicule et date/heure requis pour ouvrir le trajet.");
      return;
    }
    const isoDate = new Date(form.infraction_at).toISOString();
    onOpenChange(false);
    navigate(`/livre/history/pro?vehicle=${encodeURIComponent(form.vehicle_id)}&date=${encodeURIComponent(isoDate)}`);
  }

  async function handleFileUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = ""; // allow re-selecting the same file later
    setScanning(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/livre/fines/ocr-extract", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60000,
      });
      const ex = data.extracted || {};
      // Resolve vehicle_id from extracted plate (case-insensitive, spaces ignored)
      let vid = form.vehicle_id;
      if (!vid && ex.vehicle_plate && meta?.vehicles) {
        const norm = (s) => String(s || "").replace(/\s+/g, "").toUpperCase();
        const match = meta.vehicles.find(v => norm(v.plate) === norm(ex.vehicle_plate));
        if (match) vid = match.id;
      }
      // Merge non-null extracted fields into the form
      setForm(f => ({
        ...f,
        ref_fine:          ex.ref_fine          ?? f.ref_fine,
        authority:         ex.authority         ?? f.authority,
        country:           ex.country           ?? f.country,
        canton:            ex.canton            ?? f.canton,
        city:              ex.city              ?? f.city,
        location:          ex.location          ?? f.location,
        received_at:       ex.received_at       ?? f.received_at,
        infraction_at:     ex.infraction_at     ?? f.infraction_at,
        vehicle_id:        vid                  ?? f.vehicle_id,
        amount:            (ex.amount ?? null) !== null ? ex.amount : f.amount,
        admin_fees:        (ex.admin_fees ?? null) !== null ? ex.admin_fees : f.admin_fees,
        currency:          ex.currency          ?? f.currency,
        due_date:          ex.due_date          ?? f.due_date,
        infraction_type:   ex.infraction_type   ?? f.infraction_type,
      }));
      const filled = Object.values(ex).filter(v => v !== null && v !== undefined && v !== "").length;
      toast.success(`OCR : ${filled} champ${filled > 1 ? "s" : ""} pré-remplis — vérifiez avant d'enregistrer.`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail) || "Échec de l'analyse OCR");
    } finally { setScanning(false); }
  }

  async function submit() {
    // Light client-side checks
    if (form.amount === "" || form.amount == null) {
      toast.error("Le montant est obligatoire");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form };
      // Strip empty optional strings to keep mongo clean
      ["received_at", "due_date", "paid_at", "infraction_at",
       "ref_fine", "authority", "canton", "city", "location",
       "vehicle_id", "driver_id", "infraction_details",
       "case_owner", "internal_notes"].forEach(k => {
        if (payload[k] === "") payload[k] = null;
      });
      payload.amount = Number(payload.amount) || 0;
      payload.admin_fees = Number(payload.admin_fees) || 0;
      const res = isEdit
        ? await api.patch(`/livre/fines/${fineId}`, payload)
        : await api.post("/livre/fines", payload);
      toast.success(isEdit ? "Amende mise à jour" : `Amende créée : ${res.data.dossier_number}`);
      onSaved?.(res.data);
      onOpenChange(false);
    } catch (e) {
      toast.error(formatApiErrorDetail(e?.response?.data?.detail));
    } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col"
        data-testid="fine-form-dialog"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-3 pr-6">
            <span>{isEdit ? `Modifier l'amende` : "Nouvelle amende"}</span>
            {!isEdit && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                disabled={scanning}
                data-testid="fine-ocr-upload"
                className="h-8 text-xs text-violet-700 border-violet-300 hover:bg-violet-50"
                title="Importer un PDF ou une photo d'amende — Gemini Vision pré-remplira le formulaire"
              >
                {scanning ? (
                  <><Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> Analyse…</>
                ) : (
                  <><ScanLine className="w-3 h-3 mr-1.5" /> Importer & analyser</>
                )}
              </Button>
            )}
          </DialogTitle>
          <DialogDescription className="sr-only">
            Formulaire de saisie des informations d&apos;une amende.
          </DialogDescription>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            className="hidden"
            onChange={handleFileUpload}
            data-testid="fine-ocr-file-input"
          />
        </DialogHeader>

        {loading ? (
          <div className="flex-1 flex items-center justify-center py-16">
            <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto space-y-4 pr-1">

            {/* 1. Informations générales */}
            <section className={SECTION_CLS}>
              <h3 className={SECTION_HEAD}>Informations générales</h3>
              <div className={SECTION_BODY}>
                <Field label="Référence amende">
                  <Input data-testid="fine-form-ref" value={form.ref_fine || ""}
                         onChange={e => set("ref_fine", e.target.value)} />
                </Field>
                <Field label="Autorité émettrice">
                  <Input data-testid="fine-form-authority" value={form.authority || ""}
                         onChange={e => set("authority", e.target.value)} />
                </Field>
                <Field label="Pays">
                  <Input data-testid="fine-form-country" value={form.country || ""}
                         onChange={e => set("country", e.target.value)} />
                </Field>
                <Field label="Canton">
                  <Input data-testid="fine-form-canton" value={form.canton || ""}
                         onChange={e => set("canton", e.target.value)} />
                </Field>
                <Field label="Commune">
                  <Input data-testid="fine-form-city" value={form.city || ""}
                         onChange={e => set("city", e.target.value)} />
                </Field>
                <Field label="Date réception">
                  <Input type="date" data-testid="fine-form-received-at"
                         value={form.received_at || ""}
                         onChange={e => set("received_at", e.target.value)} />
                </Field>
                <Field label="Date & heure de l'infraction">
                  <Input type="datetime-local" data-testid="fine-form-infraction-at"
                         value={form.infraction_at || ""}
                         onChange={e => set("infraction_at", e.target.value)} />
                </Field>
                <Field label="Lieu de l'infraction" full>
                  <Input data-testid="fine-form-location" value={form.location || ""}
                         onChange={e => set("location", e.target.value)} />
                </Field>
              </div>
            </section>

            {/* 2. Véhicule & conducteur */}
            <section className={SECTION_CLS}>
              <h3 className={SECTION_HEAD}>Véhicule & conducteur</h3>
              <div className={SECTION_BODY}>
                <Field label="Véhicule">
                  <Select value={form.vehicle_id || ""}
                          onValueChange={v => set("vehicle_id", v === "_none" ? "" : v)}>
                    <SelectTrigger data-testid="fine-form-vehicle"><SelectValue placeholder="Aucun" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="_none">— Aucun —</SelectItem>
                      {(meta?.vehicles || []).map(v => (
                        <SelectItem key={v.id} value={v.id}>{v.plate}{v.model ? ` · ${v.model}` : ""}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Conducteur responsable">
                  <Select value={form.driver_id || ""}
                          onValueChange={v => set("driver_id", v === "_none" ? "" : v)}>
                    <SelectTrigger data-testid="fine-form-driver"><SelectValue placeholder="Non identifié" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="_none">— Non identifié —</SelectItem>
                      {(meta?.drivers || []).map(d => (
                        <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <div className="sm:col-span-2">
                  <IdentificationPanel
                    confidence={form.driver_confidence}
                    sources={form.driver_sources}
                    validated={form.driver_validated_manually}
                    identifying={identifying}
                    onIdentify={runIdentify}
                    onOpenTrip={openTrip}
                    canOpenTrip={!!form.vehicle_id && !!form.infraction_at}
                  />
                </div>
              </div>
            </section>

            {/* 3. Détails */}
            <section className={SECTION_CLS}>
              <h3 className={SECTION_HEAD}>Détails de l&apos;infraction</h3>
              <div className={SECTION_BODY}>
                <Field label="Type">
                  <Select value={form.infraction_type}
                          onValueChange={v => set("infraction_type", v)}>
                    <SelectTrigger data-testid="fine-form-type"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {INFRACTION_TYPES.map(t => (
                        <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Détails complémentaires" full>
                  <Textarea data-testid="fine-form-details" rows={2}
                            value={form.infraction_details || ""}
                            onChange={e => set("infraction_details", e.target.value)} />
                </Field>
              </div>
            </section>

            {/* 4. Financier */}
            <section className={SECTION_CLS}>
              <h3 className={SECTION_HEAD}>Financier</h3>
              <div className={SECTION_BODY}>
                <Field label="Montant amende">
                  <Input type="number" step="0.01" min="0" data-testid="fine-form-amount"
                         value={form.amount}
                         onChange={e => set("amount", e.target.value)} />
                </Field>
                <Field label="Frais administratifs">
                  <Input type="number" step="0.01" min="0" data-testid="fine-form-admin-fees"
                         value={form.admin_fees}
                         onChange={e => set("admin_fees", e.target.value)} />
                </Field>
                <Field label="Devise">
                  <Input data-testid="fine-form-currency" value={form.currency || "CHF"}
                         onChange={e => set("currency", e.target.value.toUpperCase().slice(0, 3))} />
                </Field>
                <Field label="Total">
                  <Input disabled value={total.toFixed(2)} />
                </Field>
                <Field label="Date limite paiement">
                  <Input type="date" data-testid="fine-form-due-date"
                         value={form.due_date || ""}
                         onChange={e => set("due_date", e.target.value)} />
                </Field>
                <Field label="Date paiement">
                  <Input type="date" data-testid="fine-form-paid-at"
                         value={form.paid_at || ""}
                         onChange={e => set("paid_at", e.target.value)} />
                </Field>
              </div>
            </section>

            {/* 5. Documents — only when editing (need a fine_id to attach to) */}
            {isEdit && (
              <DocumentsSection
                documents={form.documents}
                onUpload={uploadDoc}
                onDelete={deleteDoc}
                onDownload={downloadDoc}
              />
            )}

            {/* 6. Suivi */}
            <section className={SECTION_CLS}>
              <h3 className={SECTION_HEAD}>Suivi du dossier</h3>
              <div className={SECTION_BODY}>
                <Field label="Statut">
                  <Select value={form.status}
                          onValueChange={v => set("status", v)}>
                    <SelectTrigger data-testid="fine-form-status"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {FINE_STATUSES.map(s => (
                        <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Priorité">
                  <Select value={form.priority}
                          onValueChange={v => set("priority", v)}>
                    <SelectTrigger data-testid="fine-form-priority"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PRIORITIES.map(p => (
                        <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Responsable dossier">
                  <Input data-testid="fine-form-owner" value={form.case_owner || ""}
                         onChange={e => set("case_owner", e.target.value)} />
                </Field>
                <Field label="Notes internes" full>
                  <Textarea data-testid="fine-form-notes" rows={3}
                            value={form.internal_notes || ""}
                            onChange={e => set("internal_notes", e.target.value)} />
                </Field>
              </div>
            </section>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}
                  data-testid="fine-form-cancel">Annuler</Button>
          <Button onClick={submit} disabled={saving || loading}
                  data-testid="fine-form-submit"
                  className="bg-[#2196F3] hover:bg-[#1976D2] text-white">
            {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
            {isEdit ? "Enregistrer" : "Créer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function IdentificationPanel({
  confidence, sources, validated, identifying, onIdentify, onOpenTrip, canOpenTrip,
}) {
  const conf = Number(confidence) || 0;
  const tone = validated
    ? "bg-slate-100 border-slate-200 text-slate-700"
    : conf >= 90 ? "bg-emerald-50 border-emerald-200 text-emerald-700"
    : conf >= 70 ? "bg-blue-50 border-blue-200 text-blue-700"
    : conf > 0   ? "bg-amber-50 border-amber-200 text-amber-700"
                 : "bg-slate-50 border-slate-200 text-slate-500";
  const label = validated
    ? "Validation manuelle"
    : conf > 0 ? `Confiance ${conf}%`
               : "Aucune identification";
  return (
    <div className={`rounded-md border px-3 py-2 ${tone}`} data-testid="fine-identify-panel">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-[0.14em] font-semibold opacity-70">
            Identification automatique
          </p>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <span className="text-sm font-semibold" data-testid="fine-identify-confidence">{label}</span>
            {(sources || []).map(s => (
              <span key={s}
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-white/70 border border-current/30">
                {s}
              </span>
            ))}
          </div>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          <Button type="button" size="sm" variant="outline" onClick={onIdentify}
                  disabled={identifying}
                  data-testid="fine-identify-button"
                  className="h-8 text-xs">
            {identifying ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Sparkles className="w-3 h-3 mr-1" />}
            Identifier
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={onOpenTrip}
                  disabled={!canOpenTrip}
                  data-testid="fine-view-trip-button"
                  className="h-8 text-xs">
            <Map className="w-3 h-3 mr-1" /> Voir le trajet
          </Button>
        </div>
      </div>
    </div>
  );
}


function Field({ label, children, full }) {
  return (
    <div className={full ? "sm:col-span-2 space-y-1" : "space-y-1"}>
      <Label className="text-[11px] font-medium text-slate-600">{label}</Label>
      {children}
    </div>
  );
}

const DOCUMENT_KIND_LABELS = {
  pdf: "PDF amende",
  photo: "Photo radar",
  courrier: "Courrier",
  contestation: "Contestation",
  preuve_paiement: "Preuve paiement",
  libre: "Document libre",
};

function DocumentsSection({ documents, onUpload, onDelete, onDownload }) {
  const docs = Array.isArray(documents) ? documents : [];
  const inputRef = useRef(null);
  const [pendingKind, setPendingKind] = useState("libre");

  function pickFile(kind) {
    setPendingKind(kind);
    inputRef.current?.click();
  }

  function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    onUpload(file, pendingKind);
  }

  return (
    <section className={SECTION_CLS} data-testid="fine-documents-section">
      <h3 className={SECTION_HEAD}>Documents joints ({docs.length})</h3>
      <div className="p-3 space-y-3">
        <div className="flex flex-wrap gap-2">
          {Object.entries(DOCUMENT_KIND_LABELS).map(([k, lbl]) => (
            <Button key={k} type="button" size="sm" variant="outline"
                    onClick={() => pickFile(k)}
                    data-testid={`fine-doc-upload-${k}`}
                    className="h-7 text-[11px]">
              <Upload className="w-3 h-3 mr-1" /> {lbl}
            </Button>
          ))}
          <input
            ref={inputRef} type="file"
            accept="application/pdf,image/jpeg,image/png,image/webp,image/heic,image/heif"
            className="hidden" onChange={onFile}
            data-testid="fine-doc-file-input"
          />
        </div>

        {docs.length === 0 ? (
          <p className="text-[11px] text-slate-400 italic">Aucun document joint.</p>
        ) : (
          <div className="space-y-1.5">
            {docs.map(d => {
              const isPdf = (d.content_type || "").includes("pdf");
              return (
                <div key={d.id}
                     data-testid={`fine-doc-row-${d.id}`}
                     className="flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md bg-white border border-slate-200">
                  <div className="flex items-center gap-2 min-w-0 flex-1">
                    {isPdf ? <FileText className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />
                           : <ImageIcon className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />}
                    <div className="min-w-0">
                      <p className="text-xs text-slate-700 truncate">{d.filename}</p>
                      <p className="text-[10px] text-slate-400">
                        {DOCUMENT_KIND_LABELS[d.kind] || d.kind} · {Math.round((d.size_bytes || 0) / 1024)} ko
                      </p>
                    </div>
                  </div>
                  <Button type="button" size="sm" variant="ghost" onClick={() => onDownload(d)}
                          data-testid={`fine-doc-download-${d.id}`}
                          className="h-7 w-7 p-0 text-slate-500 hover:text-[#2196F3]">
                    <Download className="w-3.5 h-3.5" />
                  </Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => onDelete(d)}
                          data-testid={`fine-doc-delete-${d.id}`}
                          className="h-7 w-7 p-0 text-slate-500 hover:text-rose-600">
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
