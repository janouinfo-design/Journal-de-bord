/* Global header inbox for unresolved BLE driver-identification conflicts.
 *
 * - Polls /ble/sessions?status=conflict on mount, then subscribes to the
 *   realtime channel for live updates (conflict_detected / conflict_resolved).
 * - Bell icon + red badge with unresolved count.
 * - Popover panel with conflict rows (vehicle, drivers, time, confidence).
 * - Resolution Dialog inline — calls POST /ble/sessions/{id}/resolve with
 *   `source: 'header_inbox'` for audit log granularity.
 */
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Bell, Users, Truck, Clock, ShieldCheck } from "lucide-react";
import { useRealtime } from "@/hooks/useRealtime";

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("fr-CH", { hour: "2-digit", minute: "2-digit" });
  } catch { return iso; }
}

export default function ConflictInbox() {
  const [conflicts, setConflicts] = useState([]);
  const [open, setOpen] = useState(false);
  const [resolving, setResolving] = useState(null);
  const [resolveChoice, setResolveChoice] = useState("");

  async function loadConflicts() {
    try {
      const { data } = await api.get("/livre/ble/sessions",
        { params: { status: "conflict", limit: 100 } });
      setConflicts(data || []);
    } catch (e) {
      // Drivers don't have permission to list conflicts — that's expected.
      // For other roles, log so we can investigate without breaking the UI.
      if (e?.response?.status !== 403) {
        console.debug("[ConflictInbox] loadConflicts failed:", e);
      }
    }
  }
  useEffect(() => { loadConflicts(); }, []);

  // Realtime — refresh on any conflict event
  useRealtime((evt) => {
    if (["conflict_detected", "conflict_resolved", "session_opened",
         "session_updated"].includes(evt.type)) {
      loadConflicts();
    }
  });

  // Group conflicts by vehicle (we show one card per vehicle, listing drivers)
  const grouped = useMemo(() => {
    const map = new Map();
    for (const c of conflicts) {
      if (!map.has(c.vehicle_id)) map.set(c.vehicle_id, []);
      map.get(c.vehicle_id).push(c);
    }
    return Array.from(map.values()).map(arr =>
      arr.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    );
  }, [conflicts]);

  const count = grouped.length;

  async function doResolve() {
    if (!resolving || !resolveChoice) return;
    try {
      await api.post(`/livre/ble/sessions/${resolving[0].id}/resolve`, {
        winner_driver_id: resolveChoice,
        source: "header_inbox",
      });
      toast.success("Conflit résolu depuis l'inbox");
      setResolving(null); setResolveChoice("");
      loadConflicts();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            data-testid="header-conflict-inbox"
            className="w-9 h-9 rounded-md hover:bg-slate-100 flex items-center justify-center text-slate-500 relative">
            <Bell className="w-[18px] h-[18px]" />
            {count > 0 && (
              <span
                data-testid="header-conflict-badge"
                className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-[#E53935] text-white text-[10px] font-bold flex items-center justify-center ring-2 ring-white">
                {count > 99 ? "99+" : count}
              </span>
            )}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[380px] p-0" data-testid="header-conflict-panel">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <p className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Users className="w-4 h-4 text-rose-500" /> Conflits non résolus
            </p>
            <span className="text-[11px] text-slate-500" data-testid="header-conflict-count">{count}</span>
          </div>
          <div className="max-h-[60vh] overflow-y-auto">
            {count === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-slate-500" data-testid="header-conflict-empty">
                <ShieldCheck className="w-6 h-6 text-emerald-500 mx-auto mb-2" />
                Aucun conflit non résolu
              </div>
            ) : grouped.map((arr) => {
              const head = arr[0];
              return (
                <div key={head.vehicle_id} className="px-4 py-3 border-b border-slate-100 hover:bg-slate-50/60"
                  data-testid={`header-conflict-row-${head.vehicle_id}`}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Truck className="w-3.5 h-3.5 text-slate-500" />
                      <span className="font-mono text-xs font-semibold text-slate-800">{head.vehicle_plate || "—"}</span>
                    </div>
                    <span className="text-[10px] text-slate-500 flex items-center gap-1 font-mono">
                      <Clock className="w-3 h-3" /> {fmtTime(head.last_seen || head.started_at)}
                    </span>
                  </div>
                  <div className="space-y-1 mb-2">
                    {arr.map(s => (
                      <div key={s.id} className="flex items-center justify-between text-[11px] text-slate-600">
                        <span>{s.driver_name || "—"}</span>
                        <span className="font-mono">confiance {s.confidence ?? 0}</span>
                      </div>
                    ))}
                  </div>
                  <Button
                    size="sm" variant="outline"
                    className="w-full h-7 text-xs border-rose-200 text-rose-700 hover:bg-rose-50"
                    data-testid={`header-conflict-resolve-${head.vehicle_id}`}
                    onClick={() => {
                      setResolving(arr);
                      setResolveChoice(arr[0]?.driver_id || "");
                      setOpen(false);
                    }}>
                    <Users className="w-3 h-3 mr-1" /> Résoudre
                  </Button>
                </div>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>

      {/* Resolve modal */}
      <Dialog open={!!resolving} onOpenChange={(o) => { if (!o) { setResolving(null); setResolveChoice(""); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-base font-semibold flex items-center gap-2 text-rose-700">
              <Users className="w-4 h-4" /> Conflit BLE — Qui conduisait réellement ?
            </DialogTitle>
            <DialogDescription className="text-xs text-slate-500">
              Plusieurs chauffeurs détectés sur le même véhicule. Sélectionnez celui au volant.
            </DialogDescription>
          </DialogHeader>
          {resolving && (
            <div className="space-y-2 py-2">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">
                Véhicule : <span className="font-mono text-slate-700">{resolving[0]?.vehicle_plate}</span>
              </p>
              <div className="space-y-2">
                {resolving.map(s => (
                  <label key={s.id}
                    className={`flex items-center justify-between gap-3 border rounded-md p-3 cursor-pointer ${
                      resolveChoice === s.driver_id ? "border-[#2196F3] bg-blue-50" : "border-slate-200 hover:border-slate-300"
                    }`}
                    data-testid={`header-inbox-choice-${s.driver_id}`}>
                    <div className="flex items-center gap-2">
                      <input type="radio" name="inbox-winner" value={s.driver_id}
                        checked={resolveChoice === s.driver_id}
                        onChange={() => setResolveChoice(s.driver_id)} />
                      <div>
                        <p className="text-sm font-semibold text-slate-800">{s.driver_name}</p>
                        <p className="text-[11px] text-slate-500 font-mono">détections : {s.detection_count ?? 0}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-[10px] uppercase tracking-wider text-slate-400">Confiance</p>
                      <p className="font-mono text-sm">{s.confidence}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setResolving(null); setResolveChoice(""); }}>
              Annuler
            </Button>
            <Button onClick={doResolve} disabled={!resolveChoice}
              className="bg-[#2196F3] hover:bg-[#1E88E5]" data-testid="header-inbox-resolve-save">
              Valider le choix
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
