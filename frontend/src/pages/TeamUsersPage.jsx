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
import { Plus, Trash2, IdCard, Eye } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import ImpersonateDialog from "@/components/livre/ImpersonateDialog";

const ROLE_LABEL = { admin: "Admin", manager: "Gestionnaire", driver: "Chauffeur", lecture_seule: "Lecture seule" };
const EMPTY = { email: "", name: "", password: "", role: "driver" };

export default function TeamUsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState([]);
  const [impTarget, setImpTarget] = useState(null);
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

  async function changeRole(u, role) {
    try {
      await api.patch(`/livre/team/users/${u.id}`, { role });
      toast.success(`${u.email} → ${ROLE_LABEL[role] || role}`);
      load();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
  }

  async function removeUser(u) {
    if (!window.confirm(`Supprimer le compte ${u.email} ?`)) return;
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

  return (
    <div data-testid="team-users-page" className="space-y-4">
      <div className="flex justify-end">
        <Button data-testid="team-user-create-btn" onClick={() => { setForm(EMPTY); setDialog(true); }}>
          <Plus className="w-4 h-4 mr-1" /> Nouvel utilisateur
        </Button>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Nom</th>
              <th className="px-4 py-3">Rôle</th>
              <th className="px-4 py-3">Chauffeur lié</th>
              <th className="px-4 py-3">Origine</th>
              <th className="px-4 py-3">Créé le</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} data-testid={`team-user-row-${u.email}`} className="border-b border-slate-100 hover:bg-slate-50/60">
                <td className="px-4 py-3 font-medium text-slate-800">{u.email}</td>
                <td className="px-4 py-3">{u.name}</td>
                <td className="px-4 py-3">
                  <Select value={u.role} onValueChange={(r) => changeRole(u, r)}>
                    <SelectTrigger data-testid={`team-user-role-${u.email}`} className="h-8 w-[150px] text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="admin">Admin</SelectItem>
                      <SelectItem value="manager">Gestionnaire</SelectItem>
                      <SelectItem value="driver">Chauffeur</SelectItem>
                      <SelectItem value="lecture_seule">Lecture seule</SelectItem>
                    </SelectContent>
                  </Select>
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
                  {me && u.id !== me.id && u.role !== "superadmin" && !me.impersonated_by && (
                    <Button data-testid={`team-user-impersonate-${u.email}`} variant="ghost" size="sm"
                            className="text-sky-600"
                            title={`Ouvrir l'application comme ${u.name || u.email} dans un nouvel onglet`}
                            onClick={() => setImpTarget(u)}>
                      <Eye className="w-4 h-4" />
                    </Button>
                  )}
                  <Button data-testid={`team-user-delete-${u.email}`} variant="ghost" size="sm"
                          className="text-red-600" onClick={() => removeUser(u)}>
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </td>
              </tr>
            ))}
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
                  <SelectContent>
                    <SelectItem value="admin">Admin</SelectItem>
                    <SelectItem value="manager">Gestionnaire</SelectItem>
                    <SelectItem value="driver">Chauffeur</SelectItem>
                    <SelectItem value="lecture_seule">Lecture seule</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
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
    </div>
  );
}
