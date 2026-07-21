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
import { Users, Plus, Trash2 } from "lucide-react";

const ROLE_LABEL = { admin: "Admin", manager: "Gestionnaire", driver: "Chauffeur", superadmin: "Super Admin" };
const EMPTY = { email: "", name: "", password: "", role: "driver", tenant_id: "" };

export default function AdminUsersPage() {
  const [tenants, setTenants] = useState([]);
  const [users, setUsers] = useState([]);
  const [filter, setFilter] = useState("all");
  const [dialog, setDialog] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const tenantName = (tid) => tenants.find((t) => t.id === tid)?.name || tid || "—";

  const load = useCallback(async (f = filter) => {
    try {
      const { data } = await api.get("/admin/users", {
        params: f !== "all" ? { tenant_id: f } : {},
      });
      setUsers(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  }, [filter]);

  useEffect(() => {
    api.get("/admin/tenants").then(({ data }) => setTenants(data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  async function changeRole(u, role) {
    try {
      await api.patch(`/admin/users/${u.id}`, { role });
      toast.success(`${u.email} → ${ROLE_LABEL[role]}`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  }

  async function removeUser(u) {
    if (!window.confirm(`Supprimer ${u.email} ?`)) return;
    try {
      await api.delete(`/admin/users/${u.id}`);
      toast.success("Utilisateur supprimé");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  }

  async function createUser() {
    setSaving(true);
    try {
      await api.post("/admin/users", form);
      toast.success("Utilisateur créé");
      setDialog(false);
      setForm(EMPTY);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div data-testid="admin-users-page" className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400 font-semibold">Super Admin</p>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2">
            <Users className="w-6 h-6" /> Utilisateurs & rôles
          </h1>
        </div>
        <div className="flex items-center gap-3">
          <Select value={filter} onValueChange={setFilter}>
            <SelectTrigger data-testid="users-tenant-filter" className="w-[200px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Tous les clients</SelectItem>
              {tenants.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button data-testid="user-create-btn" onClick={() => { setForm({ ...EMPTY, tenant_id: tenants[0]?.id || "" }); setDialog(true); }}>
            <Plus className="w-4 h-4 mr-1" /> Nouvel utilisateur
          </Button>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Nom</th>
              <th className="px-4 py-3">Client</th>
              <th className="px-4 py-3">Rôle</th>
              <th className="px-4 py-3">Origine</th>
              <th className="px-4 py-3">Créé le</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} data-testid={`user-row-${u.email}`} className="border-b border-slate-100 hover:bg-slate-50/60">
                <td className="px-4 py-3 font-medium text-slate-800">{u.email}</td>
                <td className="px-4 py-3">{u.name}</td>
                <td className="px-4 py-3 text-slate-500">{u.role === "superadmin" ? "—" : tenantName(u.tenant_id)}</td>
                <td className="px-4 py-3">
                  {u.role === "superadmin" ? (
                    <span className="text-xs font-semibold text-purple-700">Super Admin</span>
                  ) : (
                    <Select value={u.role} onValueChange={(r) => changeRole(u, r)}>
                      <SelectTrigger data-testid={`user-role-${u.email}`} className="h-8 w-[150px] text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="admin">Admin</SelectItem>
                        <SelectItem value="manager">Gestionnaire</SelectItem>
                        <SelectItem value="driver">Chauffeur</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {u.auth_origin === "navixy" ? "SSO Navixy" : "Local"}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{u.created_at ? fmtDateTime(u.created_at) : "—"}</td>
                <td className="px-4 py-3 text-right">
                  {u.role !== "superadmin" && (
                    <Button data-testid={`user-delete-${u.email}`} variant="ghost" size="sm"
                            className="text-red-600" onClick={() => removeUser(u)}>
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={dialog} onOpenChange={setDialog}>
        <DialogContent data-testid="user-dialog">
          <DialogHeader><DialogTitle>Nouvel utilisateur</DialogTitle></DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Client</Label>
              <Select value={form.tenant_id} onValueChange={(v) => setForm({ ...form, tenant_id: v })}>
                <SelectTrigger data-testid="user-form-tenant"><SelectValue placeholder="Choisir un client" /></SelectTrigger>
                <SelectContent>
                  {tenants.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Email</Label>
                <Input data-testid="user-form-email" type="email" value={form.email}
                       onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Nom</Label>
                <Input data-testid="user-form-name" value={form.name}
                       onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Mot de passe</Label>
                <Input data-testid="user-form-password" type="password" value={form.password}
                       onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Rôle</Label>
                <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                  <SelectTrigger data-testid="user-form-role"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">Admin</SelectItem>
                    <SelectItem value="manager">Gestionnaire</SelectItem>
                    <SelectItem value="driver">Chauffeur</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(false)}>Annuler</Button>
            <Button data-testid="user-form-save" onClick={createUser}
                    disabled={saving || !form.email || !form.password || !form.tenant_id}>
              {saving ? "Création…" : "Créer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
