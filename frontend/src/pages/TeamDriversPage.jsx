import { useCallback, useEffect, useMemo, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Plus, KeySquare, Smartphone, Link2Off, Eye, Copy, Send, Search,
  MoreHorizontal, Pencil, KeyRound, Bluetooth, Truck,
} from "lucide-react";
import ImpersonateDialog from "@/components/livre/ImpersonateDialog";
import DriverSheet from "@/components/livre/DriverSheet";

const EMPTY = {
  first_name: "", last_name: "", name: "", internal_number: "", phone: "",
  email: "", active: true, ble_id: "", group: "",
  mobile_access: false, login_email: "", temp_password: "",
};

const FILTERS = [
  { value: "all", label: "Tous" },
  { value: "active", label: "Actifs" },
  { value: "inactive", label: "Inactifs" },
  { value: "with_account", label: "Compte mobile actif" },
  { value: "without_account", label: "Sans compte mobile" },
  { value: "with_ble", label: "Avec tag BLE" },
  { value: "without_ble", label: "Sans tag BLE" },
  { value: "session_active", label: "Session active" },
  { value: "pending", label: "À valider" },
  { value: "conflict", label: "Conflit" },
];

const SESSION_TINT = {
  confirmed: "text-emerald-600", automatic: "text-emerald-600",
  pending: "text-amber-600", conflict: "text-rose-600",
  open: "text-blue-600", manual: "text-violet-600", ending: "text-slate-500",
};

function fmt(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-CH", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}
function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString("fr-CH", { hour: "2-digit", minute: "2-digit" }); }
  catch { return iso; }
}

export default function TeamDriversPage() {
  const [drivers, setDrivers] = useState([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [dialog, setDialog] = useState(null); // {mode, driver?}
  const [form, setForm] = useState(EMPTY);
  const [access, setAccess] = useState(null);
  const [accessForm, setAccessForm] = useState({ email: "", password: "" });
  const [accessMode, setAccessMode] = useState("invite");
  const [inviteResult, setInviteResult] = useState(null);
  const [impTarget, setImpTarget] = useState(null);
  const [sheetDriverId, setSheetDriverId] = useState(null);
  const [tempPwDialog, setTempPwDialog] = useState(null); // {driver, temp_password}
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/livre/team/drivers");
      setDrivers(data);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return drivers.filter((d) => {
      if (q) {
        const hay = [d.name, d.first_name, d.last_name, d.email, d.account?.email, d.internal_number]
          .filter(Boolean).join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      switch (filter) {
        case "active": return d.active !== false;
        case "inactive": return d.active === false;
        case "with_account": return !!d.account && d.account.active !== false;
        case "without_account": return !d.account;
        case "with_ble": return !!d.ble_id;
        case "without_ble": return !d.ble_id;
        case "session_active": return !!d.current_session;
        case "pending": return d.current_session?.status === "pending";
        case "conflict": return d.current_session?.status === "conflict";
        default: return true;
      }
    });
  }, [drivers, search, filter]);

  function openCreate() { setForm(EMPTY); setDialog({ mode: "create" }); }
  function openEdit(d) {
    setForm({
      ...EMPTY,
      ...Object.fromEntries(["first_name", "last_name", "name", "internal_number", "phone", "email", "active", "ble_id", "group"]
        .map((k) => [k, d[k] ?? EMPTY[k]])),
    });
    setDialog({ mode: "edit", driver: d });
  }

  async function save() {
    setSaving(true);
    try {
      const payload = {
        first_name: form.first_name, last_name: form.last_name,
        name: form.name || undefined,
        internal_number: form.internal_number, phone: form.phone,
        email: form.email, active: form.active, ble_id: form.ble_id || null,
        group: form.group,
      };
      if (dialog.mode === "create") {
        const { data: created } = await api.post("/livre/team/drivers", payload);
        if (form.mobile_access && form.login_email && form.temp_password) {
          try {
            await api.post(`/livre/team/drivers/${created.id}/grant-access`,
              { email: form.login_email, password: form.temp_password });
            toast.success("Chauffeur créé avec accès mobile");
          } catch (e) {
            toast.warning(`Chauffeur créé mais accès mobile refusé : ${formatApiErrorDetail(e.response?.data?.detail)}`);
          }
        } else {
          toast.success("Chauffeur créé");
        }
      } else {
        await api.patch(`/livre/team/drivers/${dialog.driver.id}`, payload);
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
      toast.success(d.active === false ? `${d.name} réactivé` : `${d.name} désactivé — historique conservé`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function resetPassword(d) {
    if (!window.confirm(`Réinitialiser le mot de passe de ${d.name} ?\nUn mot de passe temporaire sera généré et affiché UNE SEULE FOIS.`)) return;
    try {
      const { data } = await api.post(`/livre/team/drivers/${d.id}/reset-password`);
      setTempPwDialog({ driver: d, temp_password: data.temp_password, email: data.email });
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
      toast.success(`Accès mobile activé pour ${access.name}`);
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

  async function impersonate(reason) {
    const t = impTarget;
    try {
      const { data } = await api.post(`/livre/team/users/${t.userId}/impersonate`, { reason: reason || null });
      window.open(`/driver?imp_token=${encodeURIComponent(data.token)}`, "_blank");
      toast.success(`Aperçu Console ouvert — ${t.name}`);
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
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input data-testid="drivers-search" placeholder="Rechercher (nom, e-mail, matricule)…"
                 value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8 h-9" />
        </div>
        <Select value={filter} onValueChange={setFilter}>
          <SelectTrigger data-testid="drivers-filter" className="w-[210px] h-9"><SelectValue /></SelectTrigger>
          <SelectContent>
            {FILTERS.map((f) => <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>)}
          </SelectContent>
        </Select>
        <span className="text-xs text-slate-400" data-testid="drivers-count">{filtered.length} chauffeur(s)</span>
        <Button data-testid="driver-create-btn" onClick={openCreate} className="ml-auto">
          <Plus className="w-4 h-4 mr-1" /> Nouveau chauffeur
        </Button>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Chauffeur</th>
              <th className="px-4 py-3 hidden lg:table-cell">Compte</th>
              <th className="px-4 py-3">Identification</th>
              <th className="px-4 py-3">Véhicule actuel</th>
              <th className="px-4 py-3">Session</th>
              <th className="px-4 py-3 hidden xl:table-cell">Dernier accès</th>
              <th className="px-4 py-3">Statut</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400 text-sm">Aucun chauffeur ne correspond</td></tr>
            ) : filtered.map((d) => {
              const s = d.current_session;
              return (
                <tr key={d.id} data-testid={`driver-row-${d.id}`}
                    className={`border-b border-slate-100 hover:bg-slate-50/60 cursor-pointer ${d.active === false ? "opacity-50" : ""}`}
                    onClick={() => setSheetDriverId(d.id)}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-slate-800">{d.name}</p>
                    <p className="text-[10px] text-slate-400">{d.internal_number || d.email || ""}</p>
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell">
                    {d.account ? (
                      <span className={`inline-flex items-center gap-1 text-xs ${d.account.active === false ? "text-rose-600" : "text-emerald-700"}`}>
                        <Smartphone className="w-3.5 h-3.5" /> {d.account.active === false ? "Désactivé" : "Actif"}
                      </span>
                    ) : d.pending_invitation ? (
                      <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100 text-[10px]">Invitation envoyée</Badge>
                    ) : (
                      <span className="text-xs text-slate-400">Aucun</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {d.account && <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 text-[10px] font-mono">APP</Badge>}
                      {d.ble_id && <Badge variant="outline" className="bg-cyan-50 text-cyan-700 border-cyan-200 text-[10px] font-mono">BLE</Badge>}
                      {!d.account && !d.ble_id && <span className="text-xs text-slate-400">—</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {s?.vehicle_plate ? (
                      <span className="inline-flex items-center gap-1.5"><Truck className="w-3.5 h-3.5 text-slate-400" />{s.vehicle_plate}</span>
                    ) : "—"}
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {s ? (
                      <span className={SESSION_TINT[s.status] || "text-slate-600"}>
                        {fmtTime(s.started_at)} → {s.status === "conflict" ? "Conflit"
                          : s.status === "pending" ? "À valider" : "En cours"}
                      </span>
                    ) : <span className="text-slate-400">—</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 hidden xl:table-cell">
                    {d.last_activity ? `${fmt(d.last_activity.ts)} · ${d.last_activity.kind}` : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className={d.active !== false
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200 text-[10px]"
                      : "bg-slate-100 text-slate-500 border-slate-300 text-[10px]"}>
                      {d.active !== false ? "Actif" : "Inactif"}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-7 w-7 p-0"
                                data-testid={`driver-actions-${d.id}`}>
                          <MoreHorizontal className="w-4 h-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-52">
                        <DropdownMenuItem onClick={() => setSheetDriverId(d.id)} data-testid={`driver-view-${d.id}`}>
                          <Eye className="w-3.5 h-3.5 mr-2" /> Voir la fiche
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => openEdit(d)} data-testid={`driver-edit-${d.id}`}>
                          <Pencil className="w-3.5 h-3.5 mr-2" /> Modifier
                        </DropdownMenuItem>
                        {s && (
                          <DropdownMenuItem onClick={() => setSheetDriverId(d.id)} data-testid={`driver-view-session-${d.id}`}>
                            <Truck className="w-3.5 h-3.5 mr-2" /> Voir la session
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuSeparator />
                        {!d.account && (
                          <DropdownMenuItem onClick={() => openAccess(d)} data-testid={`driver-grant-${d.id}`}>
                            <KeySquare className="w-3.5 h-3.5 mr-2" /> Activer l'accès mobile
                          </DropdownMenuItem>
                        )}
                        {d.account && (
                          <>
                            <DropdownMenuItem onClick={() => resetPassword(d)} data-testid={`driver-reset-pw-${d.id}`}>
                              <KeyRound className="w-3.5 h-3.5 mr-2" /> Réinitialiser mot de passe
                            </DropdownMenuItem>
                            {d.active !== false && d.account.active !== false && (
                              <DropdownMenuItem
                                onClick={() => setImpTarget({ name: d.name, email: d.account.email, userId: d.account.user_id })}
                                data-testid={`driver-impersonate-${d.id}`}>
                                <Smartphone className="w-3.5 h-3.5 mr-2" /> Aperçu console chauffeur
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuItem onClick={() => unlink(d)} className="text-amber-600"
                                              data-testid={`driver-unlink-${d.id}`}>
                              <Link2Off className="w-3.5 h-3.5 mr-2" /> Délier le compte
                            </DropdownMenuItem>
                          </>
                        )}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => toggleActive(d)}
                                          className={d.active !== false ? "text-rose-600" : "text-emerald-600"}
                                          data-testid={`driver-toggle-active-${d.id}`}>
                          {d.active !== false ? "Désactiver" : "Réactiver"}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Dialog création/édition */}
      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent data-testid="driver-dialog" className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{dialog?.mode === "create" ? "Nouveau chauffeur" : `Modifier ${dialog?.driver?.name}`}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-2">Identité</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>Prénom</Label>
                  <Input data-testid="driver-form-first-name" value={form.first_name}
                         onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>Nom</Label>
                  <Input data-testid="driver-form-last-name" value={form.last_name}
                         onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
                </div>
                {dialog?.mode === "edit" && !form.first_name && !form.last_name && (
                  <div className="space-y-1.5 col-span-2">
                    <Label>Nom complet</Label>
                    <Input data-testid="driver-form-name" value={form.name}
                           onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label>E-mail</Label>
                  <Input data-testid="driver-form-email" type="email" value={form.email}
                         onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>Téléphone</Label>
                  <Input data-testid="driver-form-phone" value={form.phone}
                         onChange={(e) => setForm({ ...form, phone: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>Matricule</Label>
                  <Input data-testid="driver-form-internal" value={form.internal_number}
                         onChange={(e) => setForm({ ...form, internal_number: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>Groupe / agence</Label>
                  <Input data-testid="driver-form-group" value={form.group}
                         onChange={(e) => setForm({ ...form, group: e.target.value })} />
                </div>
                <div className="flex items-center gap-2 col-span-2">
                  <Switch data-testid="driver-form-active" checked={form.active}
                          onCheckedChange={(v) => setForm({ ...form, active: v })} />
                  <Label className="text-sm">Chauffeur actif</Label>
                </div>
              </div>
            </div>

            {dialog?.mode === "create" && (
              <div>
                <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-2">Accès mobile</p>
                <div className="flex items-center gap-2 mb-2">
                  <Switch data-testid="driver-form-mobile-access" checked={form.mobile_access}
                          onCheckedChange={(v) => setForm({ ...form, mobile_access: v, login_email: v ? (form.login_email || form.email) : form.login_email })} />
                  <Label className="text-sm">Créer un compte de connexion (appli chauffeur)</Label>
                </div>
                {form.mobile_access && (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label>E-mail de connexion</Label>
                      <Input data-testid="driver-form-login-email" type="email" value={form.login_email}
                             onChange={(e) => setForm({ ...form, login_email: e.target.value })} />
                    </div>
                    <div className="space-y-1.5">
                      <Label>Mot de passe temporaire</Label>
                      <Input data-testid="driver-form-temp-password" type="text" value={form.temp_password}
                             onChange={(e) => setForm({ ...form, temp_password: e.target.value })} />
                    </div>
                  </div>
                )}
              </div>
            )}

            <div>
              <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-2">Identification BLE</p>
              <div className="space-y-1.5">
                <Label className="flex items-center gap-1.5"><Bluetooth className="w-3.5 h-3.5 text-cyan-500" /> Tag BLE porté (facultatif)</Label>
                <Input data-testid="driver-form-ble" value={form.ble_id} placeholder="A4:C1:38:XX:XX:22 — laisser vide si aucun tag"
                       onChange={(e) => setForm({ ...form, ble_id: e.target.value })} />
                <p className="text-[10px] text-slate-400">
                  APP seule, BLE seul ou APP + BLE sont supportés. Validation terrain BLE en attente.
                </p>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Annuler</Button>
            <Button data-testid="driver-form-save" onClick={save}
                    disabled={saving || (!(form.first_name.trim() || form.last_name.trim() || form.name.trim()))}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog mot de passe temporaire (affiché une seule fois) */}
      <Dialog open={!!tempPwDialog} onOpenChange={(o) => !o && setTempPwDialog(null)}>
        <DialogContent data-testid="driver-temp-pw-dialog" className="max-w-md">
          <DialogHeader>
            <DialogTitle>Mot de passe temporaire — {tempPwDialog?.driver?.name}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-slate-500">
            Affiché <strong>une seule fois</strong>. Il ne sera ni loggé ni relisible.
            Le chauffeur devra le changer à sa prochaine connexion.
          </p>
          <div className="flex items-center gap-1.5">
            <Input readOnly value={tempPwDialog?.temp_password || ""} className="font-mono"
                   onFocus={(e) => e.target.select()} data-testid="driver-temp-pw-value" />
            <Button variant="outline" size="sm" className="shrink-0"
                    onClick={() => navigator.clipboard.writeText(tempPwDialog.temp_password).then(() => toast.success("Copié"))}>
              <Copy className="w-3.5 h-3.5" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setTempPwDialog(null)} data-testid="driver-temp-pw-close">J'ai copié le mot de passe</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog accès mobile — invitation email ou mot de passe manuel */}
      <Dialog open={!!access} onOpenChange={(o) => !o && setAccess(null)}>
        <DialogContent data-testid="driver-access-dialog">
          <DialogHeader>
            <DialogTitle>Activer l'accès mobile — {access?.name}</DialogTitle>
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
                        ? `Email envoyé à ${inviteResult.email}. Lien de secours :`
                        : "SMTP non configuré — copiez ce lien et transmettez-le au chauffeur :"}
                    </p>
                    <div className="flex items-center gap-1.5">
                      <Input readOnly value={inviteResult.invite_url} data-testid="driver-invite-link"
                             className="h-8 text-[11px] font-mono bg-white" onFocus={(e) => e.target.select()} />
                      <Button data-testid="driver-invite-copy" variant="outline" size="sm" className="h-8 shrink-0"
                              onClick={() => navigator.clipboard.writeText(inviteResult.invite_url).then(() => toast.success("Lien copié"))}>
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

      <DriverSheet driverId={sheetDriverId} open={!!sheetDriverId}
                   onOpenChange={(o) => !o && setSheetDriverId(null)} onChanged={load} />
      <ImpersonateDialog target={impTarget} onOpenChange={setImpTarget} onConfirm={impersonate} />
    </div>
  );
}
