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
import { Plus, Pencil, KeySquare, Smartphone, Link2Off, Eye, Copy, Send } from "lucide-react";
import ImpersonateDialog from "@/components/livre/ImpersonateDialog";

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
  const [accessMode, setAccessMode] = useState("invite"); // invite | manual
  const [inviteResult, setInviteResult] = useState(null);
  const [impTarget, setImpTarget] = useState(null);
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

  function openAccess(d) {
    setAccess(d);
    setAccessForm({ email: d.pending_invitation?.email || d.email || "", password: "" });
    setAccessMode("invite");
    setInviteResult(null);
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

  async function sendInvite() {
    setSaving(true);
    try {
      const { data } = await api.post(`/livre/team/drivers/${access.id}/invite`, { email: accessForm.email });
      setInviteResult(data);
      if (data.email_sent) toast.success(`Invitation envoyée à ${data.email}`);
      else toast.info("Email non configuré — copiez le lien d'invitation ci-dessous");
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  function copyInviteLink() {
    navigator.clipboard.writeText(inviteResult.invite_url)
      .then(() => toast.success("Lien copié dans le presse-papier"))
      .catch(() => toast.error("Impossible de copier — sélectionnez le lien manuellement"));
  }

  async function impersonate(reason) {
    const t = impTarget;
    try {
      const { data } = await api.post(`/livre/team/users/${t.userId}/impersonate`, { reason: reason || null });
      window.open(`/driver?imp_token=${encodeURIComponent(data.token)}`, "_blank");
      toast.success(`Aperçu Console PWA ouvert — ${t.name}`);
      setImpTarget(null);
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
                  ) : d.pending_invitation ? (
                    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                      <Badge data-testid={`driver-invited-${d.id}`}
                             className="bg-amber-100 text-amber-700 hover:bg-amber-100"
                             title={`Invitation envoyée à ${d.pending_invitation.email}`}>
                        Invitation envoyée
                      </Badge>
                      <Button data-testid={`driver-reinvite-${d.id}`} variant="ghost" size="sm"
                              className="h-6 px-1.5 text-[11px] text-slate-500"
                              onClick={() => openAccess(d)}>
                        Renvoyer
                      </Button>
                    </span>
                  ) : (
                    <Button data-testid={`driver-grant-${d.id}`} variant="outline" size="sm" className="h-7 text-xs"
                            onClick={() => openAccess(d)}>
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
                            onClick={() => setImpTarget({ name: d.name, email: d.account.email, userId: d.account.user_id })}>
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

      {/* Dialog accès PWA — invitation email ou mot de passe manuel */}
      <Dialog open={!!access} onOpenChange={(o) => !o && setAccess(null)}>
        <DialogContent data-testid="driver-access-dialog">
          <DialogHeader>
            <DialogTitle>Activer l'accès PWA — {access?.name}</DialogTitle>
          </DialogHeader>
          <div className="flex gap-2">
            <Button data-testid="driver-access-mode-invite" size="sm"
                    variant={accessMode === "invite" ? "default" : "outline"}
                    onClick={() => { setAccessMode("invite"); setInviteResult(null); }}>
              <Send className="w-3.5 h-3.5 mr-1.5" /> Inviter par email
            </Button>
            <Button data-testid="driver-access-mode-manual" size="sm"
                    variant={accessMode === "manual" ? "default" : "outline"}
                    onClick={() => { setAccessMode("manual"); setInviteResult(null); }}>
              <KeySquare className="w-3.5 h-3.5 mr-1.5" /> Mot de passe manuel
            </Button>
          </div>
          {accessMode === "invite" ? (
            <>
              <p className="text-sm text-slate-500">
                Le chauffeur recevra un lien de création de mot de passe (valable 7 jours, usage unique).
                Il verra uniquement ses trajets, sa classification et ses amendes.
              </p>
              <div className="space-y-3 py-1">
                <div className="space-y-1.5">
                  <Label>Email du chauffeur</Label>
                  <Input data-testid="driver-invite-email" type="email" value={accessForm.email}
                         onChange={(e) => setAccessForm({ ...accessForm, email: e.target.value })} />
                </div>
                {inviteResult && (
                  <div data-testid="driver-invite-result"
                       className={`rounded-md border p-3 space-y-2 ${inviteResult.email_sent
                         ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
                    <p className="text-xs font-medium text-slate-700">
                      {inviteResult.email_sent
                        ? `Email envoyé à ${inviteResult.email}. Lien de secours à copier si besoin :`
                        : "Envoi d'email non configuré (SMTP) — copiez ce lien et transmettez-le au chauffeur :"}
                    </p>
                    <div className="flex items-center gap-1.5">
                      <Input readOnly value={inviteResult.invite_url} data-testid="driver-invite-link"
                             className="h-8 text-[11px] font-mono bg-white" onFocus={(e) => e.target.select()} />
                      <Button data-testid="driver-invite-copy" variant="outline" size="sm" className="h-8 shrink-0"
                              onClick={copyInviteLink}>
                        <Copy className="w-3.5 h-3.5 mr-1" /> Copier
                      </Button>
                    </div>
                  </div>
                )}
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setAccess(null)}>Fermer</Button>
                <Button data-testid="driver-invite-send" onClick={sendInvite}
                        disabled={saving || !accessForm.email}>
                  {saving ? "Envoi…" : inviteResult ? "Renvoyer l'invitation" : "Envoyer l'invitation"}
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <p className="text-sm text-slate-500">
                Crée immédiatement un compte « chauffeur » lié avec le mot de passe saisi ci-dessous.
              </p>
              <div className="space-y-3 py-1">
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
            </>
          )}
        </DialogContent>
      </Dialog>

      <ImpersonateDialog target={impTarget} onOpenChange={setImpTarget} onConfirm={impersonate} />
    </div>
  );
}
