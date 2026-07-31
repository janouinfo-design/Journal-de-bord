import { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Save } from "lucide-react";

export default function FuelSettingsPage() {
  const [s, setS] = useState(null);
  const [providersText, setProvidersText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get("/livre/fuel/settings").then(({ data }) => {
      setS(data);
      setProvidersText((data.providers || []).join(", "));
    }).catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, []);

  async function save() {
    setSaving(true);
    try {
      const { data } = await api.put("/livre/fuel/settings", {
        station_radius_m: Number(s.station_radius_m),
        score_auto: Number(s.score_auto),
        score_review: Number(s.score_review),
        time_window_min: Number(s.time_window_min),
        allocation_mode: s.allocation_mode,
        providers: providersText.split(",").map((p) => p.trim()).filter(Boolean),
      });
      setS(data);
      toast.success("Paramètres enregistrés");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  if (!s) return <p className="text-sm text-slate-400">Chargement…</p>;

  return (
    <div data-testid="fuel-settings-page" className="space-y-4 max-w-2xl">
      <div className="bg-white rounded-lg border border-slate-200 p-5 space-y-4">
        <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Seuils de rapprochement</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Seuil « rapproché automatiquement » (score /100)</Label>
            <Input data-testid="fuel-settings-score-auto" type="number" min={1} max={100}
                   value={s.score_auto} onChange={(e) => setS({ ...s, score_auto: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Seuil « contrôle recommandé » (score /100)</Label>
            <Input data-testid="fuel-settings-score-review" type="number" min={1} max={100}
                   value={s.score_review} onChange={(e) => setS({ ...s, score_review: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Fenêtre temporelle trajets (minutes)</Label>
            <Input data-testid="fuel-settings-window" type="number" min={5} max={1440}
                   value={s.time_window_min} onChange={(e) => setS({ ...s, time_window_min: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Rayon autour de la station (mètres)</Label>
            <Input data-testid="fuel-settings-radius" type="number" min={50} max={5000}
                   value={s.station_radius_m} onChange={(e) => setS({ ...s, station_radius_m: e.target.value })} />
          </div>
        </div>
        <p className="text-xs text-slate-400">
          Sous le seuil de contrôle, la transaction reste « À vérifier ». Entre les deux seuils :
          « Contrôle recommandé ». Au-dessus du seuil automatique : rapprochée sans intervention.
        </p>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-5 space-y-4">
        <p className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Répartition & fournisseurs</p>
        <div className="space-y-1.5">
          <Label>Mode de répartition des coûts</Label>
          <Select value={s.allocation_mode} onValueChange={(v) => setS({ ...s, allocation_mode: v })}>
            <SelectTrigger data-testid="fuel-settings-allocation" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="A">Mode A — coût rattaché à l'événement (trajet / plein)</SelectItem>
              <SelectItem value="B">Mode B — répartition au prorata des km (Phase 2)</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Fournisseurs de cartes (séparés par virgule)</Label>
          <Input data-testid="fuel-settings-providers" value={providersText}
                 onChange={(e) => setProvidersText(e.target.value)} />
          <p className="text-[10px] text-slate-400">
            Liste proposée à la création de carte et à l'import. Les connecteurs API fournisseurs arriveront en Phase 3.
          </p>
        </div>
      </div>

      <Button data-testid="fuel-settings-save" onClick={save} disabled={saving}
              className="bg-[#2196F3] hover:bg-[#1976D2] text-white">
        <Save className="w-4 h-4 mr-1.5" /> {saving ? "Enregistrement…" : "Enregistrer"}
      </Button>
    </div>
  );
}
