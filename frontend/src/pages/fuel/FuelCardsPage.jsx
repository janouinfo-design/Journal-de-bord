import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
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
import { CARD_STATUS, PRODUCT_LABEL, ASSIGNMENT_TYPE_LABEL } from "@/lib/fuelLabels";
import { Plus, Pencil, History, ShieldAlert } from "lucide-react";

const EMPTY_CARD = {
  provider: "", provider_account: "", card_number: "", external_card_id: "",
  assignment_type: "vehicle", vehicle_id: "", driver_id: "",
  allowed_products: [], limit_per_tx: "", limit_daily: "", limit_monthly: "",
  allowed_countries: "CH", allowed_networks: "", activated_at: "", expires_at: "", notes: "",
};

export default function FuelCardsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const [cards, setCards] = useState([]);
  const [refs, setRefs] = useState({ vehicles: [], drivers: [], providers: [], product_types: [] });
  const [dialog, setDialog] = useState(null);      // null | "create" | card (edit)
  const [form, setForm] = useState(EMPTY_CARD);
  const [statusDlg, setStatusDlg] = useState(null); // card
  const [statusForm, setStatusForm] = useState({ status: "suspended", reason: "" });
  const [assignDlg, setAssignDlg] = useState(null); // card détaillée
  const [assignForm, setAssignForm] = useState({ type: "vehicle", vehicle_id: "", driver_id: "", valid_from: "", reason: "" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.get("/livre/fuel/cards").then(({ data }) => setCards(data)).catch(() => {});
    api.get("/livre/fuel/refs").then(({ data }) => setRefs(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  function openCreate() { setForm(EMPTY_CARD); setDialog("create"); }
  function openEdit(c) {
    setForm({ ...EMPTY_CARD, ...c, card_number: "",
              allowed_countries: (c.allowed_countries || []).join(", "),
              allowed_networks: (c.allowed_networks || []).join(", "),
              limit_per_tx: c.limit_per_tx ?? "", limit_daily: c.limit_daily ?? "",
              limit_monthly: c.limit_monthly ?? "" });
    setDialog(c);
  }

  function payloadFromForm(isCreate) {
    const p = {
      provider: form.provider, provider_account: form.provider_account || null,
      external_card_id: form.external_card_id || null,
      assignment_type: form.assignment_type,
      allowed_products: form.allowed_products,
      limit_per_tx: form.limit_per_tx === "" ? null : Number(form.limit_per_tx),
      limit_daily: form.limit_daily === "" ? null : Number(form.limit_daily),
      limit_monthly: form.limit_monthly === "" ? null : Number(form.limit_monthly),
      allowed_countries: form.allowed_countries.split(",").map((s) => s.trim()).filter(Boolean),
      allowed_networks: form.allowed_networks.split(",").map((s) => s.trim()).filter(Boolean),
      activated_at: form.activated_at || null, expires_at: form.expires_at || null,
      notes: form.notes || null,
    };
    if (isCreate) {
      p.card_number = form.card_number;
      p.vehicle_id = form.vehicle_id || null;
      p.driver_id = form.driver_id || null;
    }
    return p;
  }

  async function save() {
    setSaving(true);
    try {
      if (dialog === "create") {
        await api.post("/livre/fuel/cards", payloadFromForm(true));
        toast.success("Carte créée — seuls les 4 derniers chiffres sont conservés");
      } else {
        await api.patch(`/livre/fuel/cards/${dialog.id}`, payloadFromForm(false));
        toast.success("Carte mise à jour");
      }
      setDialog(null); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  async function saveStatus() {
    setSaving(true);
    try {
      await api.post(`/livre/fuel/cards/${statusDlg.id}/status`, statusForm);
      toast.success("Statut mis à jour");
      setStatusDlg(null); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  async function openAssignments(c) {
    try {
      const { data } = await api.get(`/livre/fuel/cards/${c.id}`);
      setAssignForm({ type: "vehicle", vehicle_id: "", driver_id: "", valid_from: "", reason: "" });
      setAssignDlg(data);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function saveAssignment() {
    setSaving(true);
    try {
      await api.post(`/livre/fuel/cards/${assignDlg.id}/assignments`, {
        type: assignForm.type,
        vehicle_id: assignForm.vehicle_id || null,
        driver_id: assignForm.driver_id || null,
        valid_from: assignForm.valid_from ? new Date(assignForm.valid_from).toISOString() : null,
        reason: assignForm.reason || null,
      });
      toast.success("Affectation enregistrée");
      setAssignDlg(null); load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  const vehName = (id) => refs.vehicles.find((v) => v.id === id)?.plate || "—";
  const drvName = (id) => refs.drivers.find((d) => d.id === id)?.name || "—";

  return (
    <div data-testid="fuel-cards-page" className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400">
          Le numéro complet n'est jamais stocké ni affiché — seuls les 4 derniers chiffres sont conservés.
        </p>
        {isAdmin && (
          <Button data-testid="fuel-card-create-btn" onClick={openCreate}
                  className="bg-[#2196F3] hover:bg-[#1976D2] text-white h-9">
            <Plus className="w-4 h-4 mr-1.5" /> Nouvelle carte
          </Button>
        )}
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Fournisseur</th><th className="px-4 py-3">Carte</th>
              <th className="px-4 py-3">Type</th><th className="px-4 py-3">Affectation actuelle</th>
              <th className="px-4 py-3">Produits</th><th className="px-4 py-3">Expiration</th>
              <th className="px-4 py-3">Statut</th>
              {isAdmin && <th className="px-4 py-3 text-right">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {cards.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">Aucune carte — créez la première</td></tr>
            ) : cards.map((c) => {
              const s = CARD_STATUS[c.status] || CARD_STATUS.active;
              const a = c.current_assignment;
              return (
                <tr key={c.id} data-testid={`fuel-card-row-${c.id}`} className="border-b border-slate-100 hover:bg-slate-50/60">
                  <td className="px-4 py-3 text-xs font-medium">{c.provider}
                    {c.provider_account && <span className="block text-[10px] text-slate-400">{c.provider_account}</span>}
                  </td>
                  <td className="px-4 py-3 text-xs font-mono">•••• {c.last4}</td>
                  <td className="px-4 py-3 text-xs">{ASSIGNMENT_TYPE_LABEL[c.assignment_type] || c.assignment_type}</td>
                  <td className="px-4 py-3 text-xs">
                    {a ? (a.vehicle_plate || a.driver_name || "—") : <span className="text-slate-400 italic">Aucune</span>}
                  </td>
                  <td className="px-4 py-3 text-xs">{(c.allowed_products || []).map((p) => PRODUCT_LABEL[p] || p).join(", ") || "—"}</td>
                  <td className="px-4 py-3 text-xs">{c.expires_at ? c.expires_at.slice(0, 10) : "—"}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${s.cls}`}>{s.label}</span>
                  </td>
                  {isAdmin && (
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <Button data-testid={`fuel-card-assign-${c.id}`} variant="ghost" size="sm"
                              title="Affectations (historique)" onClick={() => openAssignments(c)}>
                        <History className="w-4 h-4" />
                      </Button>
                      <Button data-testid={`fuel-card-status-${c.id}`} variant="ghost" size="sm"
                              title="Changer le statut"
                              onClick={() => { setStatusDlg(c); setStatusForm({ status: c.status === "active" ? "suspended" : "active", reason: "" }); }}>
                        <ShieldAlert className="w-4 h-4" />
                      </Button>
                      <Button data-testid={`fuel-card-edit-${c.id}`} variant="ghost" size="sm"
                              title="Modifier" onClick={() => openEdit(c)}>
                        <Pencil className="w-4 h-4" />
                      </Button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Dialog création / édition */}
      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent data-testid="fuel-card-dialog" className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{dialog === "create" ? "Nouvelle carte carburant" : `Modifier •••• ${dialog?.last4}`}</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 py-1">
            <div className="space-y-1.5">
              <Label>Fournisseur *</Label>
              <Select value={form.provider} onValueChange={(v) => setForm({ ...form, provider: v })}>
                <SelectTrigger data-testid="fuel-card-provider"><SelectValue placeholder="Choisir…" /></SelectTrigger>
                <SelectContent>
                  {refs.providers.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Compte fournisseur</Label>
              <Input value={form.provider_account} onChange={(e) => setForm({ ...form, provider_account: e.target.value })} />
            </div>
            {dialog === "create" && (
              <div className="space-y-1.5 sm:col-span-2">
                <Label>Numéro de carte *</Label>
                <Input data-testid="fuel-card-number" value={form.card_number} placeholder="7002 1234 5678 9010"
                       onChange={(e) => setForm({ ...form, card_number: e.target.value })} />
                <p className="text-[10px] text-amber-600">Le numéro complet ne sera jamais stocké — seuls les 4 derniers chiffres resteront visibles.</p>
              </div>
            )}
            <div className="space-y-1.5">
              <Label>Identifiant externe (fournisseur)</Label>
              <Input value={form.external_card_id} onChange={(e) => setForm({ ...form, external_card_id: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Type d'affectation</Label>
              <Select value={form.assignment_type} onValueChange={(v) => setForm({ ...form, assignment_type: v })}>
                <SelectTrigger data-testid="fuel-card-assignment-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ASSIGNMENT_TYPE_LABEL).map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            {dialog === "create" && (
              <>
                <div className="space-y-1.5">
                  <Label>Véhicule principal</Label>
                  <Select value={form.vehicle_id || "none"} onValueChange={(v) => setForm({ ...form, vehicle_id: v === "none" ? "" : v })}>
                    <SelectTrigger data-testid="fuel-card-vehicle"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Aucun</SelectItem>
                      {refs.vehicles.map((v) => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Chauffeur (carte nominative)</Label>
                  <Select value={form.driver_id || "none"} onValueChange={(v) => setForm({ ...form, driver_id: v === "none" ? "" : v })}>
                    <SelectTrigger data-testid="fuel-card-driver"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Aucun</SelectItem>
                      {refs.drivers.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
            <div className="space-y-1.5 sm:col-span-2">
              <Label>Carburants autorisés</Label>
              <div className="flex flex-wrap gap-3">
                {(refs.product_types || []).map((p) => (
                  <label key={p} className="flex items-center gap-1.5 text-xs text-slate-600">
                    <Checkbox checked={form.allowed_products.includes(p)}
                              onCheckedChange={(ck) => setForm({
                                ...form,
                                allowed_products: ck ? [...form.allowed_products, p]
                                  : form.allowed_products.filter((x) => x !== p),
                              })} />
                    {PRODUCT_LABEL[p] || p}
                  </label>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Plafond / transaction (CHF)</Label>
              <Input type="number" value={form.limit_per_tx} onChange={(e) => setForm({ ...form, limit_per_tx: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Plafond journalier (CHF)</Label>
              <Input type="number" value={form.limit_daily} onChange={(e) => setForm({ ...form, limit_daily: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Plafond mensuel (CHF)</Label>
              <Input type="number" value={form.limit_monthly} onChange={(e) => setForm({ ...form, limit_monthly: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Pays autorisés (séparés par virgule)</Label>
              <Input value={form.allowed_countries} onChange={(e) => setForm({ ...form, allowed_countries: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Stations / réseaux autorisés</Label>
              <Input value={form.allowed_networks} placeholder="Migrol, Shell…"
                     onChange={(e) => setForm({ ...form, allowed_networks: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Date d'activation</Label>
              <Input type="date" value={(form.activated_at || "").slice(0, 10)}
                     onChange={(e) => setForm({ ...form, activated_at: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Date d'expiration</Label>
              <Input type="date" value={(form.expires_at || "").slice(0, 10)}
                     onChange={(e) => setForm({ ...form, expires_at: e.target.value })} />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label>Notes</Label>
              <Input value={form.notes || ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Annuler</Button>
            <Button data-testid="fuel-card-save" onClick={save}
                    disabled={saving || !form.provider || (dialog === "create" && !form.card_number)}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog statut */}
      <Dialog open={!!statusDlg} onOpenChange={(o) => !o && setStatusDlg(null)}>
        <DialogContent data-testid="fuel-card-status-dialog" className="max-w-md">
          <DialogHeader><DialogTitle>Statut — •••• {statusDlg?.last4}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-1">
            <div className="space-y-1.5">
              <Label>Nouveau statut</Label>
              <Select value={statusForm.status} onValueChange={(v) => setStatusForm({ ...statusForm, status: v })}>
                <SelectTrigger data-testid="fuel-card-status-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(CARD_STATUS).map(([v, s]) => <SelectItem key={v} value={v}>{s.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Motif</Label>
              <Input data-testid="fuel-card-status-reason" value={statusForm.reason}
                     onChange={(e) => setStatusForm({ ...statusForm, reason: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setStatusDlg(null)}>Annuler</Button>
            <Button data-testid="fuel-card-status-save" onClick={saveStatus} disabled={saving}>Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog affectations */}
      <Dialog open={!!assignDlg} onOpenChange={(o) => !o && setAssignDlg(null)}>
        <DialogContent data-testid="fuel-card-assign-dialog" className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>Affectations — •••• {assignDlg?.last4}</DialogTitle></DialogHeader>
          <div className="space-y-3 py-1">
            <div className="rounded-md border border-slate-200 divide-y divide-slate-100 max-h-44 overflow-y-auto">
              {(assignDlg?.assignments || []).length === 0 && (
                <p className="p-3 text-xs text-slate-400">Aucune affectation</p>
              )}
              {(assignDlg?.assignments || []).map((a) => (
                <div key={a.id} className="p-2.5 text-xs flex items-center justify-between">
                  <span>
                    <strong>{ASSIGNMENT_TYPE_LABEL[a.type]}</strong>{" — "}
                    {a.vehicle_id ? vehName(a.vehicle_id) : a.driver_id ? drvName(a.driver_id) : "pool"}
                  </span>
                  <span className="text-slate-400">
                    {a.valid_from ? a.valid_from.slice(0, 10) : "début"} → {a.valid_to ? a.valid_to.slice(0, 10) : "en cours"}
                  </span>
                </div>
              ))}
            </div>
            <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold pt-1">Nouvelle affectation</p>
            <div className="grid grid-cols-2 gap-3">
              <Select value={assignForm.type} onValueChange={(v) => setAssignForm({ ...assignForm, type: v })}>
                <SelectTrigger data-testid="fuel-assign-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ASSIGNMENT_TYPE_LABEL).map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
                </SelectContent>
              </Select>
              {assignForm.type === "driver" ? (
                <Select value={assignForm.driver_id || "none"}
                        onValueChange={(v) => setAssignForm({ ...assignForm, driver_id: v === "none" ? "" : v })}>
                  <SelectTrigger data-testid="fuel-assign-driver"><SelectValue placeholder="Chauffeur" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">—</SelectItem>
                    {refs.drivers.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              ) : (
                <Select value={assignForm.vehicle_id || "none"}
                        onValueChange={(v) => setAssignForm({ ...assignForm, vehicle_id: v === "none" ? "" : v })}>
                  <SelectTrigger data-testid="fuel-assign-vehicle"><SelectValue placeholder="Véhicule" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">—</SelectItem>
                    {refs.vehicles.map((v) => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
                  </SelectContent>
                </Select>
              )}
              <Input type="date" value={assignForm.valid_from}
                     onChange={(e) => setAssignForm({ ...assignForm, valid_from: e.target.value })} />
              <Input placeholder="Motif" value={assignForm.reason}
                     onChange={(e) => setAssignForm({ ...assignForm, reason: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignDlg(null)}>Fermer</Button>
            <Button data-testid="fuel-assign-save" onClick={saveAssignment} disabled={saving}>Affecter</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
