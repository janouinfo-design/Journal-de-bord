import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Building2, Plus, Pencil, KeyRound } from "lucide-react";

const EMPTY = { name: "", navixy_hash: "" };

export default function AdminTenantsPage() {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(null); // {mode:'create'|'edit', tenant?}
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/tenants");
      setTenants(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openCreate() { setForm(EMPTY); setDialog({ mode: "create" }); }
  function openEdit(t) { setForm({ name: t.name, navixy_hash: "" }); setDialog({ mode: "edit", tenant: t }); }

  async function save() {
    setSaving(true);
    try {
      if (dialog.mode === "create") {
        await api.post("/admin/tenants", {
          name: form.name, navixy_hash: form.navixy_hash || null,
        });
        toast.success("Client créé");
      } else {
        const payload = { name: form.name };
        if (form.navixy_hash) payload.navixy_hash = form.navixy_hash;
        await api.patch(`/admin/tenants/${dialog.tenant.id}`, payload);
        toast.success("Client mis à jour");
      }
      setDialog(null);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(t) {
    try {
      await api.patch(`/admin/tenants/${t.id}`, {
        status: t.status === "active" ? "suspended" : "active",
      });
      toast.success(t.status === "active" ? "Client suspendu" : "Client réactivé");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  }

  return (
    <div data-testid="admin-tenants-page" className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400 font-semibold">Super Admin</p>
          <h1 className="text-2xl font-semibold text-slate-900 flex items-center gap-2">
            <Building2 className="w-6 h-6" /> Clients (tenants)
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Chaque client = un compte maître Navixy avec sa propre clé API. Les données sont totalement isolées.
          </p>
        </div>
        <Button data-testid="tenant-create-btn" onClick={openCreate}>
          <Plus className="w-4 h-4 mr-1" /> Nouveau client
        </Button>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Client</th>
              <th className="px-4 py-3">Statut</th>
              <th className="px-4 py-3">Clé API Navixy</th>
              <th className="px-4 py-3">Compte Navixy</th>
              <th className="px-4 py-3">Utilisateurs</th>
              <th className="px-4 py-3">Véhicules</th>
              <th className="px-4 py-3">Trajets</th>
              <th className="px-4 py-3">Dernière sync</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-400">Chargement…</td></tr>
            ) : tenants.map((t) => (
              <tr key={t.id} data-testid={`tenant-row-${t.id}`} className="border-b border-slate-100 hover:bg-slate-50/60">
                <td className="px-4 py-3 font-medium text-slate-800">{t.name}
                  {t.id === "default" && <span className="ml-2 text-[10px] text-slate-400">(défaut)</span>}
                </td>
                <td className="px-4 py-3">
                  <Badge variant={t.status === "active" ? "default" : "destructive"}
                         className={t.status === "active" ? "bg-emerald-100 text-emerald-700 hover:bg-emerald-100" : ""}>
                    {t.status === "active" ? "Actif" : "Suspendu"}
                  </Badge>
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">
                  {t.has_navixy_hash ? t.navixy_hash_masked : <span className="text-amber-600">non configurée</span>}
                </td>
                <td className="px-4 py-3 text-slate-500 text-xs">
                  {t.navixy_login || "—"}
                  {t.navixy_master_user_id ? <span className="text-slate-400"> · #{t.navixy_master_user_id}</span> : null}
                </td>
                <td className="px-4 py-3">{t.stats?.users ?? 0}</td>
                <td className="px-4 py-3">{t.stats?.vehicles ?? 0}</td>
                <td className="px-4 py-3">{t.stats?.trips ?? 0}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{t.last_sync_at ? fmtDateTime(t.last_sync_at) : "—"}</td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <Button data-testid={`tenant-edit-${t.id}`} variant="ghost" size="sm" onClick={() => openEdit(t)}>
                    <Pencil className="w-4 h-4" />
                  </Button>
                  {t.id !== "default" && (
                    <Button data-testid={`tenant-toggle-${t.id}`} variant="ghost" size="sm"
                            className={t.status === "active" ? "text-red-600" : "text-emerald-600"}
                            onClick={() => toggleStatus(t)}>
                      {t.status === "active" ? "Suspendre" : "Réactiver"}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent data-testid="tenant-dialog">
          <DialogHeader>
            <DialogTitle>{dialog?.mode === "create" ? "Nouveau client" : `Modifier « ${dialog?.tenant?.name} »`}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Nom du client</Label>
              <Input data-testid="tenant-name-input" value={form.name}
                     onChange={(e) => setForm({ ...form, name: e.target.value })}
                     placeholder="Ex : Transport Dupont SA" />
            </div>
            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5" /> Clé API Navixy {dialog?.mode === "edit" && "(laisser vide pour conserver)"}
              </Label>
              <Input data-testid="tenant-hash-input" value={form.navixy_hash}
                     onChange={(e) => setForm({ ...form, navixy_hash: e.target.value })}
                     placeholder="Clé API du compte maître Navixy" />
              <p className="text-xs text-slate-400">
                La clé est validée auprès de l'API Navixy et le compte maître est identifié automatiquement.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>Annuler</Button>
            <Button data-testid="tenant-save-btn" onClick={save} disabled={saving || !form.name.trim()}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
