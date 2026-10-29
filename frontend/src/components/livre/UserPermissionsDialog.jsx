import { useEffect, useMemo, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { KeyRound, RotateCcw, ShieldAlert } from "lucide-react";
import { ROLE_LABEL, ROLE_HINT } from "@/lib/roles";
import PermissionGroup from "@/components/livre/PermissionGroup";

// Réplique de access_control.expand / effective_permissions pour l'aperçu local avant enregistrement.
function expand(set, known) {
  const out = new Set(set);
  for (const p of set) {
    const [res, action] = p.split(".");
    if (action === "admin") ["edit", "view"].forEach((a) => known.has(`${res}.${a}`) && out.add(`${res}.${a}`));
    else if (action === "edit" && known.has(`${res}.view`)) out.add(`${res}.view`);
  }
  return out;
}

function computeEffective(role, template, grant, revoke, catalog) {
  const known = new Set(catalog.permissions.map((p) => p.code));
  const byCode = Object.fromEntries(catalog.permissions.map((p) => [p.code, p]));
  const eff = expand(new Set([...template, ...grant]), known);
  revoke.forEach((p) => eff.delete(p));
  return new Set([...eff].filter((p) => byCode[p]?.available && !(role === "lecture_seule" && byCode[p]?.write)));
}

export default function UserPermissionsDialog({ target, catalog, onClose, onSaved }) {
  const [data, setData] = useState(null); // { template, override, effective }
  const [grant, setGrant] = useState(new Set());
  const [revoke, setRevoke] = useState(new Set());
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get(`/livre/team/users/${target.id}/permissions`).then(({ data: d }) => {
      setData(d);
      setGrant(new Set(d.override.grant));
      setRevoke(new Set(d.override.revoke));
    }).catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, [target.id]);

  const role = target.role;
  const template = useMemo(() => new Set(data?.template || []), [data]);
  const effective = useMemo(() => data ? computeEffective(role, template, grant, revoke, catalog) : new Set(),
    [data, role, template, grant, revoke, catalog]);
  const sensitiveGranted = [...grant].filter((p) => catalog.permissions.find((x) => x.code === p)?.sensitive && !template.has(p));
  const blockedSensitive = catalog.sensitive_blocked_roles.includes(role);

  const groups = useMemo(() => {
    const mods = [...catalog.modules, { code: null, label: "Plateforme (entreprise)" }];
    return mods.map((m) => ({ ...m, perms: catalog.permissions.filter((p) => p.module === m.code && p.available) }))
      .filter((g) => g.perms.length);
  }, [catalog]);

  function stateOf(p) {
    const isEff = effective.has(p.code);
    const inT = template.has(p.code);
    let disabled = false, disabledReason = "";
    if (p.sensitive && blockedSensitive && !inT) { disabled = true; disabledReason = "sensible — non attribuable à ce rôle"; }
    if (role === "lecture_seule" && p.write) { disabled = true; disabledReason = "lecture seule — aucune écriture"; }
    let badge = "non", badgeCls = "bg-slate-100 text-slate-400";
    if (revoke.has(p.code)) { badge = "retirée"; badgeCls = "bg-red-100 text-red-700"; }
    else if (grant.has(p.code)) { badge = "accordée"; badgeCls = "bg-sky-100 text-sky-700"; }
    else if (isEff && inT) { badge = "rôle"; badgeCls = "bg-emerald-100 text-emerald-700"; }
    else if (isEff) { badge = "implicite"; badgeCls = "bg-emerald-50 text-emerald-600"; }
    return { effective: isEff, disabled, disabledReason, badge, badgeCls };
  }

  function toggle(p, on) {
    const g = new Set(grant), r = new Set(revoke);
    const [res, action] = p.code.split(".");
    if (on) {
      r.delete(p.code);
      if (!template.has(p.code)) g.add(p.code);
    } else {
      g.delete(p.code);
      r.add(p.code);
      // retirer « view » retire aussi edit / admin (qui l'impliquent)
      if (action === "view") ["edit", "admin"].forEach((a) => { const c = `${res}.${a}`; if (effective.has(c)) { g.delete(c); r.add(c); } });
      if (action === "edit" && effective.has(`${res}.admin`)) { g.delete(`${res}.admin`); r.add(`${res}.admin`); }
    }
    setGrant(g); setRevoke(r);
  }

  async function save(payload) {
    setSaving(true);
    try {
      await api.put(`/livre/team/users/${target.id}/permissions`, payload);
      toast.success(`Permissions de ${target.email} enregistrées`);
      onSaved?.();
      onClose();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  }

  const changed = data && (JSON.stringify([...grant].sort()) !== JSON.stringify(data.override.grant)
    || JSON.stringify([...revoke].sort()) !== JSON.stringify(data.override.revoke));

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="user-permissions-dialog" className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><KeyRound className="w-5 h-5" /> Permissions — {target.name || target.email}</DialogTitle>
          <DialogDescription>
            Rôle <strong>{ROLE_LABEL[role] || role}</strong> : {ROLE_HINT[role]} Le rôle est un modèle ; cochez ou décochez pour
            ajuster individuellement. Les modules coupés pour l'entreprise n'apparaissent pas.
          </DialogDescription>
        </DialogHeader>

        {!data ? <p className="text-sm text-slate-400 py-6 text-center">Chargement…</p> : (
          <div className="space-y-4 py-1">
            {groups.map((g) => (
              <PermissionGroup key={g.code || "platform"} title={g.label} perms={g.perms} state={stateOf} onToggle={toggle} />
            ))}
            {sensitiveGranted.length > 0 && (
              <div data-testid="sensitive-grant-warning" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 space-y-2">
                <p className="flex items-center gap-1.5 font-semibold"><ShieldAlert className="w-4 h-4" /> Permissions sensibles accordées hors rôle : {sensitiveGranted.join(", ")}</p>
                {sensitiveGranted.includes("positions.view") && (
                  <p>Cet utilisateur verra les positions GPS, traces et localisations détaillées. L'attribution est journalisée dans l'audit.</p>
                )}
                <Input data-testid="permissions-reason" value={reason} onChange={(e) => setReason(e.target.value)}
                       placeholder="Motif (recommandé, conservé dans l'audit)" className="h-8 bg-white" />
              </div>
            )}
          </div>
        )}

        <DialogFooter className="items-center sm:justify-between">
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <span data-testid="permissions-summary">{effective.size} effectives · +{grant.size} / −{revoke.size}</span>
            {(grant.size > 0 || revoke.size > 0) && (
              <Button data-testid="permissions-reset" variant="ghost" size="sm" className="h-7 text-xs"
                      onClick={() => save({ grant: [], revoke: [] })} disabled={saving}>
                <RotateCcw className="w-3.5 h-3.5 mr-1" /> Revenir au rôle
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Annuler</Button>
            <Button data-testid="permissions-save" disabled={!changed || saving}
                    onClick={() => save({ grant: [...grant], revoke: [...revoke], reason: reason || null })}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
