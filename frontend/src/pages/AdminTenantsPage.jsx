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
import { Building2, Plus, Pencil, KeyRound, RefreshCw, AlertTriangle } from "lucide-react";

const EMPTY = { name: "", navixy_hash: "" };

function syncHealth(t) {
  if (!t.has_navixy_hash) return { code: "no_key", label: "Clé non configurée", cls: "bg-amber-100 text-amber-700" };
  if (!t.last_sync_at) return { code: "never", label: "Jamais synchronisé", cls: "bg-slate-100 text-slate-500" };
  if (t.last_sync_result?.error) return { code: "error", label: "Échec", cls: "bg-red-100 text-red-700" };
  return { code: "ok", label: "OK", cls: "bg-emerald-100 text-emerald-700" };
}

export default function AdminTenantsPage() {
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialog, setDialog] = useState(null); // {mode:'create'|'edit', tenant?}
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(null);

  async function syncNow(t) {
    setSyncing(t.id);
    try {
      const { data } = await api.post(`/admin/tenants/${t.id}/sync`);
      const r = data.result || {};
      toast.success(`Synchro « ${t.name} » OK — ${r.trackers ?? 0} véhicules, ${(r.trips_new ?? 0) + (r.trips_updated ?? 0)} trajets`);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSyncing(null);
      load();
    }
  }

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

      {tenants.some((t) => syncHealth(t).code === "error") && (
        <div data-testid="sync-alert-banner"
             className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>
            Synchronisation Navixy en échec pour :{" "}
            <strong>{tenants.filter((t) => syncHealth(t).code === "error").map((t) => t.name).join(", ")}</strong>
            {" "}— vérifiez la clé API ou relancez manuellement.
          </span>
        </div>
      )}

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
              <th className="px-4 py-3">Synchro Navixy</th>
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
                <td className="px-4 py-3">
                  {(() => {
                    const h = syncHealth(t);
                    return (
                      <div className="flex items-center gap-2">
                        <span data-testid={`sync-status-${t.id}`}
                              className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${h.cls}`}
                              title={h.code === "error" ? String(t.last_sync_result?.error || "") : undefined}>
                          {h.label}
                        </span>
                        <span className="text-[11px] text-slate-400 whitespace-nowrap">
                          {t.last_sync_at ? fmtDateTime(t.last_sync_at) : ""}
                        </span>
                        {t.has_navixy_hash && (
                          <Button data-testid={`sync-now-${t.id}`} variant="ghost" size="sm"
                                  className="h-7 px-1.5" disabled={syncing === t.id}
                                  onClick={() => syncNow(t)} title="Synchroniser maintenant">
                            <RefreshCw className={`w-3.5 h-3.5 ${syncing === t.id ? "animate-spin" : ""}`} />
                          </Button>
                        )}
                      </div>
                    );
                  })()}
                  {syncHealth(t).code === "error" && (
                    <p className="mt-1 text-[11px] text-red-600 max-w-[260px] truncate"
                       title={String(t.last_sync_result?.error || "")}>
                      {String(t.last_sync_result?.error || "")}
                    </p>
                  )}
                </td>
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
                <KeyRound className="w-3.5 h-3.5" /> Clé API Navixy du client {dialog?.mode === "edit" && "(laisser vide pour conserver)"}
              </Label>
              <Input data-testid="tenant-hash-input" value={form.navixy_hash}
                     onChange={(e) => setForm({ ...form, navixy_hash: e.target.value })}
                     placeholder="Clé API du compte maître Navixy" />
              <p className="text-xs text-slate-400">
                Chaque client a sa propre clé API. Générez-la de préférence depuis le
                <strong> compte principal Navixy du client</strong> (ou un utilisateur voyant toute la flotte),
                sinon la synchronisation sera partielle. La clé est validée auprès de l'API Navixy
                et le compte principal est identifié automatiquement — même si la clé vient d'un sous-utilisateur.
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
