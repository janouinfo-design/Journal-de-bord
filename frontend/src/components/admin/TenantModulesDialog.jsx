import { useMemo, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Boxes, ShieldCheck, Lock } from "lucide-react";

const CATEGORY = {
  core: { label: "Cœur", hint: "Socle du Journal de bord." },
  business: { label: "Métier", hint: "Modules fonctionnels livrés." },
  reserved: { label: "Réservés", hint: "Prévus au catalogue — sans effet tant que le module n'est pas livré." },
};

export const MODE_META = {
  legacy: { label: "Legacy", hint: "Comportement historique par rôle. Les modules et permissions n'ont aucun effet côté API.", cls: "bg-slate-100 text-slate-600" },
  shadow: { label: "Observation", hint: "Rien n'est bloqué : chaque refus qui surviendrait est journalisé dans l'audit (access.shadow_deny).", cls: "bg-amber-100 text-amber-700" },
  enforce: { label: "Appliqué", hint: "Modules coupés et permissions manquantes sont réellement refusés (403).", cls: "bg-emerald-100 text-emerald-700" },
};

// Un module dont une dépendance est OFF est forcé OFF (même règle que le backend).
function cascade(flags, modules) {
  const out = { ...flags };
  let changed = true;
  while (changed) {
    changed = false;
    for (const m of modules) {
      if (out[m.code] && m.depends_on.some((d) => !out[d])) { out[m.code] = false; changed = true; }
    }
  }
  return out;
}

export default function TenantModulesDialog({ tenant, catalog, onClose, onSaved }) {
  const modules = catalog.modules;
  const initialFlags = useMemo(() => cascade(
    Object.fromEntries(modules.map((m) => [m.code, tenant.modules_enabled ? !!tenant.modules_enabled[m.code] : m.legacy_default])),
    modules), [modules, tenant]);
  const [flags, setFlags] = useState(initialFlags);
  const [mode, setMode] = useState(tenant.access_control_mode_effective || "legacy");
  const [saving, setSaving] = useState(false);
  const [confirmEnforce, setConfirmEnforce] = useState(false);

  const byCat = useMemo(() => modules.reduce((acc, m) => { (acc[m.category] ||= []).push(m); return acc; }, {}), [modules]);
  const labelOf = (code) => modules.find((m) => m.code === code)?.label || code;
  const activeCount = Object.values(flags).filter(Boolean).length;
  const flagsChanged = modules.some((m) => flags[m.code] !== initialFlags[m.code]);
  const modeChanged = mode !== (tenant.access_control_mode_effective || "legacy");

  function toggle(code, value) {
    setFlags((f) => cascade({ ...f, [code]: value }, modules));
  }

  async function save() {
    setSaving(true);
    try {
      if (flagsChanged) await api.put(`/admin/tenants/${tenant.id}/modules`, { modules_enabled: flags });
      if (modeChanged) await api.patch(`/admin/tenants/${tenant.id}`, { access_control_mode: mode });
      toast.success(`Modules & licences de « ${tenant.name} » enregistrés`);
      onSaved?.();
      onClose();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  }

  function onSaveClick() {
    if (modeChanged && mode === "enforce") setConfirmEnforce(true);
    else save();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="tenant-modules-dialog" className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Boxes className="w-5 h-5" /> Modules & licences — {tenant.name}
          </DialogTitle>
          <DialogDescription>
            Ce que ce client a souscrit. Un module coupé disparaît de la navigation et, en mode « Appliqué », est refusé par l'API
            quelles que soient les permissions des utilisateurs.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-1">
          <div className="rounded-lg border border-slate-200 p-4 space-y-2 bg-slate-50/60">
            <Label className="flex items-center gap-1.5 text-xs uppercase tracking-wide text-slate-500">
              <ShieldCheck className="w-3.5 h-3.5" /> Mode de contrôle d'accès
            </Label>
            <Select value={mode} onValueChange={setMode}>
              <SelectTrigger data-testid="tenant-mode-select" className="w-[260px] bg-white"><SelectValue /></SelectTrigger>
              <SelectContent>
                {catalog.modes.map((m) => (
                  <SelectItem key={m} value={m} data-testid={`tenant-mode-option-${m}`}>{MODE_META[m].label} ({m})</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-slate-500">{MODE_META[mode]?.hint}</p>
          </div>

          {["core", "business", "reserved"].map((cat) => byCat[cat] && (
            <div key={cat}>
              <div className="flex items-baseline justify-between mb-2">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-semibold">{CATEGORY[cat].label}</p>
                <p className="text-[11px] text-slate-400">{CATEGORY[cat].hint}</p>
              </div>
              <div className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
                {byCat[cat].map((m) => {
                  const blockedBy = m.depends_on.filter((d) => !flags[d]);
                  return (
                    <div key={m.code} className="flex items-center justify-between gap-4 px-4 py-2.5">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-800 flex items-center gap-2">
                          {m.label}
                          {cat === "reserved" && (
                            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-slate-400">
                              <Lock className="w-3 h-3" /> réservé
                            </span>
                          )}
                        </p>
                        <p className="text-[11px] text-slate-400 font-mono">
                          {m.code}
                          {m.depends_on.length > 0 && ` · nécessite ${m.depends_on.map(labelOf).join(", ")}`}
                        </p>
                        {blockedBy.length > 0 && (
                          <p className="text-[11px] text-amber-600">Forcé OFF : {blockedBy.map(labelOf).join(", ")} désactivé</p>
                        )}
                      </div>
                      <Switch data-testid={`module-switch-${m.code}`} checked={!!flags[m.code]}
                              disabled={blockedBy.length > 0}
                              onCheckedChange={(v) => toggle(m.code, v)} />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <DialogFooter className="items-center sm:justify-between">
          <p data-testid="modules-active-count" className="text-xs text-slate-500">{activeCount} / {modules.length} modules actifs</p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Annuler</Button>
            <Button data-testid="tenant-modules-save" onClick={onSaveClick} disabled={saving || (!flagsChanged && !modeChanged)}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>

      <AlertDialog open={confirmEnforce} onOpenChange={setConfirmEnforce}>
        <AlertDialogContent data-testid="enforce-confirm-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>Passer « {tenant.name} » en mode Appliqué ?</AlertDialogTitle>
            <AlertDialogDescription>
              Les contrôles deviennent bloquants pour tous les utilisateurs de ce client : modules coupés et permissions
              manquantes renverront une erreur 403. Vérifiez d'abord les refus observés en mode Observation.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction data-testid="enforce-confirm-btn" onClick={() => { setConfirmEnforce(false); save(); }}>
              Confirmer le mode Appliqué
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Dialog>
  );
}
