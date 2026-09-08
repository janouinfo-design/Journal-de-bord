import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Loader2, Car } from "lucide-react";

const MODE_LABELS = {
  ALL: "Tous les véhicules du compte",
  SELECTED: "Véhicules sélectionnés",
  SINGLE: "Un seul véhicule",
};

export const DriverVehicleAccessCard = ({ driverId }) => {
  const { user } = useAuth();
  const canEdit = user?.role === "admin" || user?.role === "superadmin";
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [fleet, setFleet] = useState([]);
  const [mode, setMode] = useState("ALL");
  const [selectedIds, setSelectedIds] = useState([]);
  const [defaultId, setDefaultId] = useState(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/livre/team/drivers/${driverId}/vehicle-access`);
      setFleet(data.fleet || []);
      setMode(data.mode || "ALL");
      setSelectedIds(data.vehicle_ids || []);
      setDefaultId(data.default_vehicle_id || null);
    } catch (e) {
      toast.error("Impossible de charger les accès véhicules");
    } finally {
      setLoading(false);
    }
  }, [driverId]);

  useEffect(() => { load(); }, [load]);

  const filteredFleet = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return fleet;
    return fleet.filter((v) =>
      (v.plate || "").toLowerCase().includes(s) ||
      (v.label || "").toLowerCase().includes(s) ||
      (v.model || "").toLowerCase().includes(s));
  }, [fleet, search]);

  const defaultOptions = useMemo(() => {
    if (mode === "ALL") return fleet;
    return fleet.filter((v) => selectedIds.includes(v.id));
  }, [mode, fleet, selectedIds]);

  function toggleVehicle(id) {
    setSelectedIds((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      if (defaultId && !next.includes(defaultId)) setDefaultId(null);
      return next;
    });
  }

  function changeMode(m) {
    setMode(m);
    if (m === "SINGLE") {
      const kept = selectedIds.length ? [selectedIds[0]] : [];
      setSelectedIds(kept);
      setDefaultId(kept[0] || null);
    } else if (m === "SELECTED") {
      if (defaultId && !selectedIds.includes(defaultId)) setDefaultId(null);
    }
  }

  async function save() {
    if (mode === "SELECTED" && selectedIds.length === 0) {
      toast.error("Sélectionnez au moins un véhicule");
      return;
    }
    if (mode === "SINGLE" && selectedIds.length !== 1) {
      toast.error("Choisissez le véhicule attribué");
      return;
    }
    setSaving(true);
    try {
      await api.put(`/livre/team/drivers/${driverId}/vehicle-access`, {
        mode,
        vehicle_ids: mode === "ALL" ? [] : selectedIds,
        default_vehicle_id: defaultId,
      });
      toast.success("Les accès véhicules de ce chauffeur ont été mis à jour.");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Enregistrement refusé");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="rounded-md border border-slate-200 px-3 py-4 bg-white flex justify-center">
        <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="rounded-md border border-slate-200 px-3 py-3 bg-white space-y-3"
      data-testid="driver-vehicle-access-card">
      <RadioGroup value={mode} onValueChange={changeMode} disabled={!canEdit}
        className="space-y-1.5">
        {Object.entries(MODE_LABELS).map(([m, label]) => (
          <div key={m} className="flex items-center gap-2">
            <RadioGroupItem value={m} id={`va-mode-${m}`}
              data-testid={`driver-access-mode-${m.toLowerCase()}`} disabled={!canEdit} />
            <Label htmlFor={`va-mode-${m}`} className="text-sm font-normal cursor-pointer">
              {label}
            </Label>
          </div>
        ))}
      </RadioGroup>

      {mode === "ALL" && (
        <p className="text-xs text-slate-500" data-testid="driver-access-all-hint">
          Ce chauffeur peut utiliser tous les véhicules de ce compte.
        </p>
      )}

      {(mode === "SELECTED" || mode === "SINGLE") && (
        <div className="space-y-2">
          <Input placeholder="Rechercher un véhicule..." value={search}
            onChange={(e) => setSearch(e.target.value)} className="h-8 text-sm"
            data-testid="driver-access-vehicle-search" />
          {mode === "SELECTED" && (
            <p className="text-xs font-medium text-slate-600"
              data-testid="driver-access-selected-count">
              {selectedIds.length} véhicule{selectedIds.length > 1 ? "s" : ""} sélectionné{selectedIds.length > 1 ? "s" : ""}
            </p>
          )}
          <div className="max-h-48 overflow-y-auto rounded border border-slate-100 divide-y divide-slate-50">
            {filteredFleet.map((v) => {
              const checked = selectedIds.includes(v.id);
              return (
                <label key={v.id}
                  className="flex items-center gap-2.5 px-2.5 py-1.5 text-sm cursor-pointer hover:bg-slate-50">
                  <Checkbox checked={checked} disabled={!canEdit}
                    data-testid={`driver-access-vehicle-${v.id}`}
                    onCheckedChange={() => {
                      if (mode === "SINGLE") {
                        setSelectedIds([v.id]);
                        setDefaultId(v.id);
                      } else {
                        toggleVehicle(v.id);
                      }
                    }} />
                  <Car className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                  <span className="truncate">{v.plate}{v.label && v.label !== v.plate ? ` — ${v.label}` : ""}</span>
                </label>
              );
            })}
            {filteredFleet.length === 0 && (
              <p className="text-xs text-slate-400 px-2.5 py-2">Aucun véhicule trouvé.</p>
            )}
          </div>
        </div>
      )}

      {mode !== "SINGLE" && (
        <div className="space-y-1">
          <p className="text-xs text-slate-500">Véhicule par défaut</p>
          <Select value={defaultId || "none"} disabled={!canEdit}
            onValueChange={(v) => setDefaultId(v === "none" ? null : v)}>
            <SelectTrigger className="h-8 text-sm" data-testid="driver-access-default-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Aucun</SelectItem>
              {defaultOptions.map((v) => (
                <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {mode === "SINGLE" && selectedIds.length === 1 && (
        <p className="text-xs text-slate-500" data-testid="driver-access-single-hint">
          Véhicule attribué : ce véhicule sera proposé automatiquement.
        </p>
      )}

      {canEdit ? (
        <Button size="sm" onClick={save} disabled={saving}
          data-testid="driver-access-save-btn">
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />}
          Enregistrer
        </Button>
      ) : (
        <p className="text-xs text-slate-400" data-testid="driver-access-readonly">
          Modification réservée aux administrateurs.
        </p>
      )}
    </div>
  );
};

export default DriverVehicleAccessCard;
