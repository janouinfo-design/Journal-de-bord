import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Link2, Loader2, ShieldCheck } from "lucide-react";

/* Correspondance tenant Journal → tenant Energy (FAIL-CLOSED).
   Sans valeur configurée : AUCUN appel Energy, jamais de fallback global.
   Modification admin uniquement, auditée. Le token Energy n'apparaît jamais ici. */
export default function EnergyTenantCard() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [cfg, setCfg] = useState(null);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/livre/energy/tenant-mapping")
      .then(r => { setCfg(r.data); setValue(r.data.energy_tenant_id || ""); })
      .catch(() => setCfg({ configured: false, energy_tenant_id: null, forbidden: true }));
  }, []);

  async function save(next) {
    setSaving(true);
    try {
      const { data } = await api.put("/livre/energy/tenant-mapping",
        { energy_tenant_id: next });
      setCfg(data);
      setValue(data.energy_tenant_id || "");
      toast.success(data.configured
        ? "Correspondance tenant Energy enregistrée (auditée)"
        : "Correspondance supprimée — appels Energy bloqués (fail-closed)");
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Erreur lors de l'enregistrement");
    } finally {
      setSaving(false);
    }
  }

  if (!cfg) {
    return (
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="settings-energy-tenant-card">
        <div className="py-6 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div>
      </Card>
    );
  }

  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5" data-testid="settings-energy-tenant-card">
      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Énergie & carburant</p>
      <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2 mt-0.5">
        <Link2 className="w-4 h-4 text-slate-400" /> Tenant Energy
      </h2>
      <p className="text-xs text-slate-500 mt-2">
        Identifiant de ce client dans le module Énergie externe. Sans valeur,
        <strong> aucun appel Energy n&apos;est émis</strong> (fail-closed) — jamais de
        tenant par défaut ni de valeur héritée d&apos;un autre client.
      </p>
      <div className="flex items-center gap-2 mt-3 flex-wrap">
        <Badge variant="outline" data-testid="settings-energy-tenant-state"
               className={cfg.configured
                 ? "bg-emerald-50 text-emerald-600 border-emerald-200 text-[10px] px-2 py-0.5"
                 : "bg-amber-50 text-amber-700 border-amber-200 text-[10px] px-2 py-0.5"}>
          {cfg.configured ? "Configuré" : "Non configuré — appels Energy bloqués"}
        </Badge>
        <Badge variant="outline" className="bg-slate-50 text-slate-500 border-slate-200 text-[10px] px-2 py-0.5 flex items-center gap-1">
          <ShieldCheck className="w-3 h-3" /> Fail-closed · isolé par client · audité
        </Badge>
      </div>
      <div className="flex items-center gap-2 mt-3 max-w-md">
        <Input value={value} placeholder="ex. paas_13588"
               onChange={(e) => setValue(e.target.value)}
               disabled={!isAdmin || saving}
               data-testid="settings-energy-tenant-input" />
        <Button size="sm" variant="outline"
                disabled={!isAdmin || saving || (value.trim() === (cfg.energy_tenant_id || ""))}
                onClick={() => save(value.trim() || null)}
                data-testid="settings-energy-tenant-save">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : "Enregistrer"}
        </Button>
      </div>
      {!isAdmin && (
        <p className="text-[11px] text-slate-400 mt-2" data-testid="settings-energy-tenant-readonly">
          Modification réservée aux administrateurs.
        </p>
      )}
    </Card>
  );
}
