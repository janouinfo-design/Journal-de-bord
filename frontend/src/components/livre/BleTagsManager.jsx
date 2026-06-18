import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { Tag, Loader2, Plus, Trash2, Wifi } from "lucide-react";

/**
 * BLE Tags management dialog.
 *
 * - Lists existing tags (GET /livre/ble/tags)
 * - Add a tag (POST /livre/ble/tags { vehicle_id, identifier })
 * - Delete a tag (DELETE /livre/ble/tags/{id})
 *
 * Admin only. Vehicle list is fetched from /livre/vehicles.
 */
export default function BleTagsManager({ open, onOpenChange, vehicles = [] }) {
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ identifier: "", vehicle_id: "" });

  async function reload() {
    setLoading(true);
    try {
      const { data } = await api.get("/livre/ble/tags");
      setTags(Array.isArray(data) ? data : (data?.tags ?? []));
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Impossible de charger les tags");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) reload();
  }, [open]);

  async function addTag(e) {
    e?.preventDefault?.();
    const identifier = form.identifier.trim();
    if (!identifier || !form.vehicle_id) {
      toast.error("Identifiant et véhicule obligatoires");
      return;
    }
    setCreating(true);
    try {
      await api.post("/livre/ble/tags", {
        identifier,
        vehicle_id: form.vehicle_id,
      });
      toast.success(`Tag « ${identifier} » enregistré`);
      setForm({ identifier: "", vehicle_id: "" });
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Création refusée");
    } finally {
      setCreating(false);
    }
  }

  async function removeTag(tag) {
    if (!window.confirm(`Supprimer le tag « ${tag.identifier} » ?`)) return;
    try {
      await api.delete(`/livre/ble/tags/${tag.id}`);
      toast.success("Tag supprimé");
      reload();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Suppression refusée");
    }
  }

  function plateOf(vehicleId) {
    const v = vehicles.find((x) => x.id === vehicleId);
    return v ? `${v.plate}${v.model ? " — " + v.model : ""}` : vehicleId;
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" data-testid="ble-tags-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Tag className="w-5 h-5 text-[#2196F3]" /> Gestion des tags BLE
          </DialogTitle>
          <DialogDescription>
            Associez chaque tag Bluetooth à un véhicule. L&apos;identifiant doit
            correspondre exactement au nom diffusé par le tag (visible avec
            <span className="font-mono text-slate-700"> nRF Connect </span>
            par exemple).
          </DialogDescription>
        </DialogHeader>

        {/* Add form */}
        <form
          onSubmit={addTag}
          className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2 items-end border border-slate-200 rounded-md p-3 bg-slate-50/50"
        >
          <div>
            <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">
              Identifiant du tag
            </label>
            <Input
              value={form.identifier}
              onChange={(e) => setForm({ ...form, identifier: e.target.value })}
              placeholder="ex. BUS35 ou LOGI-A4B7"
              data-testid="ble-tags-identifier"
              autoFocus
            />
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-slate-500 block mb-1">
              Véhicule
            </label>
            <Select
              value={form.vehicle_id}
              onValueChange={(v) => setForm({ ...form, vehicle_id: v })}
            >
              <SelectTrigger data-testid="ble-tags-vehicle">
                <SelectValue placeholder="Choisir un véhicule" />
              </SelectTrigger>
              <SelectContent>
                {vehicles.map((v) => (
                  <SelectItem key={v.id} value={v.id}>
                    {v.plate}{v.model ? ` — ${v.model}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            type="submit"
            disabled={creating}
            className="bg-[#2196F3] hover:bg-[#1E88E5] text-white"
            data-testid="ble-tags-add"
          >
            {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4 mr-1" />}
            Ajouter
          </Button>
        </form>

        {/* List */}
        <div className="mt-2 border border-slate-200 rounded-md overflow-hidden">
          <table className="w-full text-sm" data-testid="ble-tags-table">
            <thead className="bg-slate-50">
              <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                <th className="text-left px-3 py-2 font-medium">Identifiant</th>
                <th className="text-left px-3 py-2 font-medium">Véhicule</th>
                <th className="text-right px-3 py-2 font-medium w-24">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={3} className="py-6 text-center text-slate-400">
                  <Loader2 className="w-4 h-4 animate-spin inline mr-2" /> Chargement…
                </td></tr>
              )}
              {!loading && tags.length === 0 && (
                <tr><td colSpan={3} className="py-8 text-center text-slate-400">
                  <Wifi className="w-5 h-5 mx-auto mb-2 opacity-50" />
                  Aucun tag enregistré pour le moment.
                </td></tr>
              )}
              {!loading && tags.map((t) => (
                <tr key={t.id}
                    data-testid={`ble-tags-row-${t.identifier}`}
                    className="border-t border-slate-100 hover:bg-slate-50/50">
                  <td className="px-3 py-2 font-mono text-slate-800">{t.identifier}</td>
                  <td className="px-3 py-2 text-slate-700">{plateOf(t.vehicle_id)}</td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      variant="ghost" size="sm"
                      onClick={() => removeTag(t)}
                      className="h-7 text-rose-600 hover:bg-rose-50"
                      data-testid={`ble-tags-delete-${t.identifier}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="ble-tags-close">
            Fermer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
