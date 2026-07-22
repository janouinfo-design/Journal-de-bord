import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Plus, Pencil, KeySquare, Smartphone, Link2Off, Eye } from "lucide-react";

const EMPTY = {
  name: "", internal_number: "", phone: "", email: "", active: true,
  ibutton_id: "", rfid_id: "", ble_id: "", group: "",
};

export default function TeamDriversPage() {
  const [drivers, setDrivers] = useState([]);
  const [dialog, setDialog] = useState(null); // {mode, driver?}
  const [form, setForm] = useState(EMPTY);
  const [access, setAccess] = useState(null); // driver for grant-access dialog
  const [accessForm, setAccessForm] = useState({ email: "", password: "" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/livre/team/drivers");
      setDrivers(data);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  function openCreate() { setForm(EMPTY); setDialog({ mode: "create" }); }
  function openEdit(d) {
    setForm({ ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).map((k) => [k, d[k] ?? EMPTY[k]])) });
    setDialog({ mode: "edit", driver: d });
  }

  async function save() {
    setSaving(true);
    try {
      if (dialog.mode === "create") {
        await api.post("/livre/team/drivers", form);
        toast.success("Chauffeur créé");
      } else {
        await api.patch(`/livre/team/drivers/${dialog.driver.id}`, form);
        toast.success("Chauffeur mis à jour");
      }
      setDialog(null);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  async function toggleActive(d) {
    try {
      await api.patch(`/livre/team/drivers/${d.id}`, { active: !(d.active ?? true) });
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function grantAccess() {
    setSaving(true);
    try {
      await api.post(`/livre/team/drivers/${access.id}/grant-access`, accessForm);
      toast.success(`Accès PWA activé pour ${access.name}`);
      setAccess(null);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  async function impersonate(d) {
    try {
      const { data } = await api.post(`/livre/team/users/${d.account.user_id}/impersonate`);
      window.open(`/driver?imp_token=${encodeURIComponent(data.token)}`, "_blank");
      toast.success(`Aperçu Console PWA ouvert — ${d.name}`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function unlink(d) {
    if (!window.confirm(`Retirer l'accès de ${d.name} ? (le compte n'est pas supprimé)`)) return;
    try {
      await api.post(`/livre/team/drivers/${d.id}/unlink-user`);
      toast.success("Compte délié");
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  return (
    <div data-testid="team-drivers-page" className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400">
          Les chauffeurs Navixy sont importés automatiquement à chaque synchronisation (sans compte de connexion).
        </p>
        <Button data-testid="driver-create-btn" onClick={openCreate}>
          <Plus className="w-4 h-4 mr-1" /> Nouveau chauffeur
        </Button>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Chauffeur</th>
              <th className="px-4 py-3">N° interne</th>
              <th className="px-4 py-3">Téléphone</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Identifiants</th>
              <th className="px-4 py-3">Navixy</th>
              <th className="px-4 py-3">Accès PWA</th>
              <th className="px-4 py-3">Actif</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {drivers.map((d) => (
              <tr key={d.id} data-testid={`driver-row-${d.id}`}
                  className={`border-b border-slate-100 hover:bg-slate-50/60 ${d.active === false ? "opacity-50" : ""}`}>
                <td className="px-4 py-3 font-medium text-slate-800">{d.name}
                  {d.group && <span className="ml-2 text-[10px] text-slate-400">({d.group})</span>}
                </td>
                <td className="px-4 py-3 text-xs">{d.internal_number || "—"}</td>
                <td className="px-4 py-3 text-xs">{d.phone || "—"}</td>
                <td className="px-4 py-3 text-xs">{d.email || "—"}</td>
                <td className="px-4 py-3 text-[11px] font-mono text-slate-500">
                  {[d.ibutton_id && `iBtn:${d.ibutton_id}`, d.rfid_id && `RFID:${d.rfid_id}`, d.ble_id && `BLE:${d.ble_id}`]
                    .filter(Boolean).join(" · ") || "—"}
                </td>
                <td className="px-4 py-3">
                  {d.navixy_employee_id
                    ? <Badge className="bg-sky-100 text-sky-700 hover:bg-sky-100">#{d.navixy_employee_id}</Badge>
                    : <span className="text-xs text-slate-400">Manuel</span>}
                </td>
                <td className="px-4 py-3">
                  {d.account ? (
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
                      <Smartphone className="w-3.5 h-3.5" /> {d.account.email}
                    </span>
                  ) : (
                    <Button data-testid={`driver-grant-${d.id}`} variant="outline" size="sm" className="h-7 text-xs"
                            onClick={() => { setAccess(d); setAccessForm({ email: d.email || "", password: "" }); }}>
                      <KeySquare className="w-3.5 h-3.5 mr-1" /> Activer
                    </Button>
                  )}
                </td>
                <td className="px-4 py-3">
                  <Switch data-testid={`driver-active-${d.id}`} checked={d.active !== false}
                          onCheckedChange={() => toggleActive(d)} />
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {d.account && d.active !== false ? (
                    <Button data-testid={`driver-impersonate-${d.id}`} variant="ghost" size="sm"
                            className="text-sky-600"
                            title={`Ouvrir la Console PWA comme ${d.name} dans un nouvel onglet`}
                            onClick={() => impersonate(d)}>
                      <Eye className="w-4 h-4" />
                    </Button>
                  ) : (
                    <span data-testid={`driver-no-access-${d.id}`}
                          className="text-[10px] text-slate-300 italic mr-1">Aucun accès PWA actif</span>
                  )}
                  <Button data-testid={`driver-edit-${d.id}`} variant="ghost" size="sm" onClick={() => openEdit(d)}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  {d.account && (
                    <Button data-testid={`driver-unlink-${d.id}`} variant="ghost" size="sm"
                            className="text-amber-600" title="Délier le compte" onClick={() => unlink(d)}>
                      <Link2Off className="w-4 h-4" />
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Dialog création/édition */}
      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent data-testid="driver-dialog" className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{dialog?.mode === "create" ? "Nouveau chauffeur" : `Modifier ${dialog?.driver?.name}`}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5 col-span-2">
                <Label>Nom complet *</Label>
                <Input data-testid="driver-form-name" value={form.name}
                       onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>N° interne</Label>
                <Input data-testid="driver-form-internal" value={form.internal_number}
                       onChange={(e) => setForm({ ...form, internal_number: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Groupe / agence</Label>
                <Input data-testid="driver-form-group" value={form.group}
                       onChange={(e) => setForm({ ...form, group: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Téléphone</Label>
                <Input data-testid="driver-form-phone" value={form.phone}
                       onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Email (facultatif)</Label>
                <Input data-testid="driver-form-email" type="email" value={form.email}
                       onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>iButton / Dallas</Label>
                <Input data-testid="driver-form-ibutton" value={form.ibutton_id}
                       onChange={(e) => setForm({ ...form, ibutton_id: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>RFID</Label>
                <Input data-testid="driver-form-rfid" value={form.rfid_id}
                       onChange={(e) => setForm({ ...form, rfid_id: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Badge BLE</Label>
                <Input data-testid="driver-form-ble" value={form.ble_id}
                       onChange={(e) => setForm({ ...form, ble_id: e.target.value })} />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Annuler</Button>
            <Button data-testid="driver-form-save" onClick={save} disabled={saving || !form.name.trim()}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog accès PWA */}
      <Dialog open={!!access} onOpenChange={(o) => !o && setAccess(null)}>
        <DialogContent data-testid="driver-access-dialog">
          <DialogHeader>
            <DialogTitle>Activer l'accès PWA — {access?.name}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-500">
            Crée un compte « chauffeur » lié : il verra uniquement ses trajets, sa classification et ses amendes.
          </p>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label>Email de connexion</Label>
              <Input data-testid="driver-access-email" type="email" value={accessForm.email}
                     onChange={(e) => setAccessForm({ ...accessForm, email: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label>Mot de passe</Label>
              <Input data-testid="driver-access-password" type="password" value={accessForm.password}
                     onChange={(e) => setAccessForm({ ...accessForm, password: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAccess(null)}>Annuler</Button>
            <Button data-testid="driver-access-save" onClick={grantAccess}
                    disabled={saving || !accessForm.email || !accessForm.password}>
              {saving ? "Activation…" : "Activer l'accès"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
