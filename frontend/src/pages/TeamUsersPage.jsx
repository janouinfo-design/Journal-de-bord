import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Plus, Trash2, IdCard, Eye, KeyRound, UserX, UserCheck } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import ImpersonateDialog from "@/components/livre/ImpersonateDialog";
import UserPermissionsDialog from "@/components/livre/UserPermissionsDialog";
import { ROLE_LABEL, TENANT_ROLE_OPTIONS, ROLE_HINT } from "@/lib/roles";

const EMPTY = { email: "", name: "", password: "", role: "driver" };

function RoleItems() {
  return TENANT_ROLE_OPTIONS.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>);
}

export default function TeamUsersPage() {
  const { user: me, can } = useAuth();
  const [users, setUsers] = useState([]);
  const [impTarget, setImpTarget] = useState(null);
  const [permTarget, setPermTarget] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [dialog, setDialog] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/livre/team/users");
      setUsers(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function openPermissions(u) {
    try {
      const cat = catalog || (await api.get("/livre/team/permissions/catalog")).data;
      setCatalog(cat);
      setPermTarget(u);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function patchUser(u, payload, okMsg) {
    try {
      await api.patch(`/livre/team/users/${u.id}`, payload);
      toast.success(okMsg);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  function changeRole(u, role) {
    const extra = u.permissions_override ? " — les permissions personnalisées sont réinitialisées" : "";
    patchUser(u, { role }, `${u.email} → ${ROLE_LABEL[role] || role}${extra}`);
  }

  function toggleActive(u) {
    const deactivate = u.active !== false;
    if (deactivate && !window.confirm(`Désactiver le compte ${u.email} ? L'accès est coupé immédiatement, l'historique est conservé.`)) return;
    patchUser(u, { active: !deactivate }, deactivate ? "Compte désactivé" : "Compte réactivé");
  }

  async function removeUser(u) {
    if (!window.confirm(`Supprimer DÉFINITIVEMENT le compte ${u.email} ?\n\nPréférez « Désactiver » pour conserver l'historique et l'audit.`)) return;
    try {
      await api.delete(`/livre/team/users/${u.id}`);
      toast.success("Compte supprimé");
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function impersonate(reason) {
    const u = impTarget;
    try {
      const { data } = await api.post(`/livre/team/users/${u.id}/impersonate`, { reason: reason || null });
      const path = u.role === "driver" ? "/driver" : "/livre/dashboard";
      window.open(`${path}?imp_token=${encodeURIComponent(data.token)}`, "_blank");
      toast.success(`Aperçu ouvert dans un nouvel onglet — ${u.name || u.email}`);
      setImpTarget(null);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function createUser() {
    setSaving(true);
    try {
      await api.post("/livre/team/users", form);
      toast.success("Compte créé");
      setDialog(false);
      setForm(EMPTY);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  const canEdit = can("users.edit");
  const canPerms = can("users.permissions");

  return (
    <div data-testid="team-users-page" className="space-y-4">
      <div className="flex justify-end">
        {canEdit && (
          <Button data-testid="team-user-create-btn" onClick={() => { setForm(EMPTY); setDialog(true); }}>
            <Plus className="w-4 h-4 mr-1" /> Nouvel utilisateur
          </Button>
        )}
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Nom</th>
              <th className="px-4 py-3">Rôle</th>
              <th className="px-4 py-3">Permissions</th>
              <th className="px-4 py-3">Statut</th>
              <th className="px-4 py-3">Chauffeur lié</th>
              <th className="px-4 py-3">Origine</th>
              <th className="px-4 py-3">Créé le</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const ov = u.permissions_override;
              const inactive = u.active === false;
              return (
              <tr key={u.id} data-testid={`team-user-row-${u.email}`}
                  className={`border-b border-slate-100 hover:bg-slate-50/60 ${inactive ? "text-slate-400" : ""}`}>
                <td className="px-4 py-3 font-medium text-slate-800">{u.email}</td>
                <td className="px-4 py-3">{u.name}</td>
                <td className="px-4 py-3">
                  <Select value={u.role} onValueChange={(r) => changeRole(u, r)} disabled={!canEdit}>
                    <SelectTrigger data-testid={`team-user-role-${u.email}`} className="h-8 w-[190px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent><RoleItems /></SelectContent>
                  </Select>
                </td>
                <td className="px-4 py-3">
                  <button data-testid={`team-user-permissions-${u.email}`} type="button"
                          onClick={() => openPermissions(u)} disabled={!canPerms && !can("users.view")}
                          className="inline-flex items-center gap-1.5 text-xs hover:underline" title="Voir / ajuster les permissions">
                    <KeyRound className="w-3.5 h-3.5 text-slate-400" />
                    {ov ? (
                      <span className="rounded-full bg-sky-100 text-sky-700 px-2 py-0.5 font-semibold">
                        Personnalisées +{(ov.grant || []).length} / −{(ov.revoke || []).length}
                      </span>
                    ) : <span className="text-slate-500">Selon le rôle</span>}
                  </button>
                </td>
                <td className="px-4 py-3">
                  <span data-testid={`team-user-status-${u.email}`}
                        className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${inactive ? "bg-slate-100 text-slate-500" : "bg-emerald-100 text-emerald-700"}`}>
                    {inactive ? "Désactivé" : "Actif"}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {u.linked_driver ? (
                    <span className="inline-flex items-center gap-1">
                      <IdCard className="w-3.5 h-3.5" /> {u.linked_driver.name}
                    </span>
                  ) : "—"}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {u.auth_origin === "navixy" ? "SSO Navixy" : "Local"}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{u.created_at ? fmtDateTime(u.created_at) : "—"}</td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {me && u.id !== me.id && u.role !== "superadmin" && !me.impersonated_by && can("users.impersonate") && !inactive && (
                    <Button data-testid={`team-user-impersonate-${u.email}`} variant="ghost" size="sm"
                            className="text-sky-600"
                            title={`Ouvrir l'application comme ${u.name || u.email} dans un nouvel onglet`}
                            onClick={() => setImpTarget(u)}>
                      <Eye className="w-4 h-4" />
                    </Button>
                  )}
                  {canEdit && me && u.id !== me.id && (
                    <Button data-testid={`team-user-toggle-active-${u.email}`} variant="ghost" size="sm"
                            className={inactive ? "text-emerald-600" : "text-amber-600"}
                            title={inactive ? "Réactiver le compte" : "Désactiver le compte (recommandé : conserve l'historique)"}
                            onClick={() => toggleActive(u)}>
                      {inactive ? <UserCheck className="w-4 h-4" /> : <UserX className="w-4 h-4" />}
                    </Button>
                  )}
                  {canEdit && (
                    <Button data-testid={`team-user-delete-${u.email}`} variant="ghost" size="sm"
                            className="text-red-600" title="Supprimer définitivement (préférez la désactivation)"
                            onClick={() => removeUser(u)}>
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  )}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog open={dialog} onOpenChange={setDialog}>
        <DialogContent data-testid="team-user-dialog">
          <DialogHeader><DialogTitle>Nouvel utilisateur</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Email</Label>
                <Input data-testid="team-user-form-email" type="email" value={form.email}
                       onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Nom</Label>
                <Input data-testid="team-user-form-name" value={form.name}
                       onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Mot de passe</Label>
                <Input data-testid="team-user-form-password" type="password" value={form.password}
                       onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Rôle</Label>
                <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                  <SelectTrigger data-testid="team-user-form-role"><SelectValue /></SelectTrigger>
                  <SelectContent><RoleItems /></SelectContent>
                </Select>
              </div>
            </div>
            <p data-testid="team-user-form-role-hint" className="text-xs text-slate-500">{ROLE_HINT[form.role]}</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(false)}>Annuler</Button>
            <Button data-testid="team-user-form-save" onClick={createUser}
                    disabled={saving || !form.email || !form.password}>
              {saving ? "Création…" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ImpersonateDialog target={impTarget} onOpenChange={setImpTarget} onConfirm={impersonate} />
      {permTarget && catalog && (
        <UserPermissionsDialog target={permTarget} catalog={catalog} onClose={() => setPermTarget(null)} onSaved={load} />
      )}
    </div>
  );
}
