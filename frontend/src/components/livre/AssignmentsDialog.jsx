import { useEffect, useState } from "react";
import { api, fmtDateTime } from "@/lib/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { Users, Plus, Trash2, Loader2 } from "lucide-react";

export default function AssignmentsDialog({ vehicle, drivers, onChanged, canEdit }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    driver_id: "",
    from_date: "",
    to_date: "",
    is_primary: false,
  });

  async function load() {
    if (!vehicle) return;
    setLoading(true);
    try {
      const { data } = await api.get(`/livre/assignments?vehicle_id=${vehicle.id}`);
      setRows(data);
    } finally { setLoading(false); }
  }

  useEffect(() => { if (open) load(); /* eslint-disable-next-line */ }, [open, vehicle?.id]);

  async function add() {
    if (!form.driver_id) {
      toast.error("Sélectionnez un chauffeur");
      return;
    }
    try {
      const payload = {
        vehicle_id: vehicle.id,
        driver_id: form.driver_id,
        is_primary: !!form.is_primary,
      };
      if (form.from_date) payload.from_date = new Date(form.from_date).toISOString();
      if (form.to_date) payload.to_date = new Date(form.to_date + "T23:59:59").toISOString();
      const { data } = await api.post(`/livre/assignments`, payload);
      // Optimistic UI: insert the new row immediately
      if (data?.assignment) {
        setRows((prev) => {
          let next = prev.slice();
          if (data.assignment.is_primary) {
            next = next.map((r) => ({ ...r, is_primary: false }));
          }
          return [data.assignment, ...next];
        });
      }
      toast.success(`Affectation ajoutée · ${data.trips_reassigned} trajets réattribués`);
      setForm({ driver_id: "", from_date: "", to_date: "", is_primary: false });
      load();
      onChanged?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Refusé");
    }
  }

  async function remove(id) {
    // Optimistic UI: remove immediately
    setRows((prev) => prev.filter((r) => r.id !== id));
    try {
      const { data } = await api.delete(`/livre/assignments/${id}`);
      toast.success(`Affectation supprimée · ${data.trips_reassigned} trajets réattribués`);
      load();
      onChanged?.();
    } catch {
      toast.error("Refusé");
      load(); // rollback by reloading from server
    }
  }

  function driverName(id) {
    return drivers.find(d => d.id === id)?.name || id;
  }

  if (!vehicle) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="outline" size="sm" className="h-8 text-xs"
          data-testid={`assignments-open-${vehicle.plate.replace(/\s+/g, "-")}`}
        >
          <Users className="w-3 h-3 mr-1.5" /> Chauffeurs
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base font-semibold">
            Affectations · {vehicle.plate}
            <span className="text-xs font-normal text-slate-500 ml-2">{vehicle.model}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="bg-slate-50 border border-slate-200 rounded-md p-4 space-y-3">
            <p className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Nouvelle affectation</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <Label className="text-[10px] uppercase tracking-wider text-slate-400">Chauffeur</Label>
                <Select value={form.driver_id} onValueChange={(v) => setForm({ ...form, driver_id: v })} disabled={!canEdit}>
                  <SelectTrigger
                    className="mt-1"
                    data-testid="assignments-driver-select"
                  ><SelectValue placeholder="—" /></SelectTrigger>
                  <SelectContent>
                    {drivers.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-wider text-slate-400">Du (optionnel)</Label>
                <Input type="date" value={form.from_date}
                  data-testid="assignments-from-date"
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, from_date: e.target.value })}
                  className="mt-1" />
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-wider text-slate-400">Au (optionnel)</Label>
                <Input type="date" value={form.to_date}
                  data-testid="assignments-to-date"
                  disabled={!canEdit}
                  onChange={(e) => setForm({ ...form, to_date: e.target.value })}
                  className="mt-1" />
              </div>
              <div className="col-span-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.is_primary}
                    disabled={!canEdit}
                    onCheckedChange={(v) => setForm({ ...form, is_primary: v })}
                    id="primary"
                  />
                  <Label htmlFor="primary" className="text-sm text-slate-700">Chauffeur principal</Label>
                </div>
                <Button
                  disabled={!canEdit} onClick={add}
                  data-testid="assignments-add-btn"
                  className="bg-[#2196F3] hover:bg-[#1E88E5] text-white" size="sm"
                >
                  <Plus className="w-3.5 h-3.5 mr-1" /> Ajouter
                </Button>
              </div>
            </div>
          </div>

          <div>
            <p className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">Affectations actuelles</p>
            {loading ? (
              <div className="py-6 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" /></div>
            ) : rows.length === 0 ? (
              <p className="text-sm text-slate-500 italic py-3">Aucune affectation</p>
            ) : (
              <div className="border border-slate-200 rounded-md overflow-hidden">
                <table className="w-full text-sm" data-testid="assignments-table">
                  <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
                    <tr>
                      <th className="text-left py-2 px-3">Chauffeur</th>
                      <th className="text-left py-2 px-3">Période</th>
                      <th className="text-center py-2 px-3">Principal</th>
                      <th className="text-center py-2 px-3">Source</th>
                      <th className="text-right py-2 px-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(r => (
                      <tr key={r.id} className="border-t border-slate-100">
                        <td className="py-2 px-3 font-medium text-slate-800">{driverName(r.driver_id)}</td>
                        <td className="py-2 px-3 text-xs text-slate-600">
                          {r.from_date ? fmtDateTime(r.from_date) : <span className="text-slate-400">∞</span>}
                          {" → "}
                          {r.to_date ? fmtDateTime(r.to_date) : <span className="text-slate-400">∞</span>}
                        </td>
                        <td className="py-2 px-3 text-center">
                          {r.is_primary && (
                            <span className="inline-flex bg-[#2196F3] text-white text-[10px] px-2 py-0.5 rounded-full">Primary</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-center">
                          <span className={`text-[10px] uppercase tracking-wider ${r.source === "navixy" ? "text-[#1976D2]" : "text-slate-500"}`}>
                            {r.source}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-right">
                          {canEdit && (
                            <Button
                              variant="ghost" size="sm"
                              data-testid={`assignments-delete-${r.id}`}
                              onClick={() => remove(r.id)}
                              className="h-7 w-7 p-0 text-red-500 hover:text-red-700 hover:bg-red-50"
                            ><Trash2 className="w-3.5 h-3.5" /></Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Fermer</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
