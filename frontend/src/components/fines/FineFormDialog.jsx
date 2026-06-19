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
import { Loader2 } from "lucide-react";
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
  const [form, setForm] = useState(BLANK);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
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

  const total = useMemo(
    () => (Number(form.amount) || 0) + (Number(form.admin_fees) || 0),
    [form.amount, form.admin_fees],
  );

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
          <DialogTitle>{isEdit ? `Modifier l'amende` : "Nouvelle amende"}</DialogTitle>
          <DialogDescription className="sr-only">
            Formulaire de saisie des informations d&apos;une amende.
          </DialogDescription>
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

            {/* 5. Suivi */}
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

function Field({ label, children, full }) {
  return (
    <div className={full ? "sm:col-span-2 space-y-1" : "space-y-1"}>
      <Label className="text-[11px] font-medium text-slate-600">{label}</Label>
      {children}
    </div>
  );
}
