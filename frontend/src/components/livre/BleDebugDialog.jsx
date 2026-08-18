import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { Loader2, Bug, Copy, RefreshCw, Radio, Eraser, Link as LinkIcon } from "lucide-react";

/* Local sub-component imports (kept here to keep this file self-contained). */
function PairAliasDialog({ open, onOpenChange, aliasCanon, aliasRaw, onDone }) {
  const [tags, setTags] = useState([]);
  const [tagId, setTagId] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    api.get("/livre/ble/tags").then(r => setTags(r.data || []));
  }, [open]);
  async function submit() {
    const tag = tags.find(t => t.id === tagId);
    if (!tag) return;
    setBusy(true);
    try {
      await api.post("/livre/ble/aliases", {
        alias_id: aliasCanon, tag_identifier: tag.identifier,
        label: `Apparié depuis Debug BLE (raw=${aliasRaw || aliasCanon})`,
      });
      toast.success("Alias enregistré — les prochaines détections seront reconnues");
      onDone?.();
      onOpenChange(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    } finally { setBusy(false); }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="ble-pair-dialog">
        <DialogHeader>
          <DialogTitle>Apparier ce signal à un véhicule</DialogTitle>
          <DialogDescription>
            Ce signal n&apos;a pas été reconnu. Choisissez à quel tag (donc véhicule) il correspond — les futures détections seront automatiquement résolues.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="text-xs">
            <span className="text-slate-500">Identifiant capté :</span>{" "}
            <span className="font-mono text-[#2196F3]">{aliasCanon}</span>
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Tag de destination</label>
            <select
              value={tagId}
              onChange={(e) => setTagId(e.target.value)}
              data-testid="ble-pair-tag-select"
              className="w-full border border-slate-200 rounded-md px-2 py-1.5 text-sm">
              <option value="">— Choisissez un tag —</option>
              {tags.map(t => (
                <option key={t.id} value={t.id}>
                  {t.identifier} {t.label ? `· ${t.label}` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button onClick={submit} disabled={!tagId || busy}
                  data-testid="ble-pair-submit"
                  className="bg-[#2196F3] hover:bg-[#1976D2] text-white">
            {busy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <LinkIcon className="w-4 h-4 mr-2" />}
            Apparier
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const POLL_MS = 3000;

/**
 * Live BLE detection debug panel.
 *
 * - Polls /livre/ble/debug/recent-detections every 3s
 * - Shows raw + canonical identifier, RSSI, manufacturer data, service UUIDs,
 *   platform, driver
 * - One-click copy of the canonical identifier ready to paste into "Add tag"
 *
 * Useful when a new beacon (e.g. KBPro on iPhone) is not being matched —
 * the admin opens this panel, sees the canonical form, and registers it.
 */
export default function BleDebugDialog({ open, onOpenChange }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [auto, setAuto] = useState(true);
  const [pairOpen, setPairOpen] = useState(false);
  const [pairTarget, setPairTarget] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/livre/ble/debug/recent-detections", { params: { limit: 100 } });
      setRows(Array.isArray(data) ? data : []);
    } catch (e) {
      console.debug("[BleDebug] fetch failed:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    load();
    if (!auto) return;
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [open, auto, load]);

  function copyCanon(canon) {
    try {
      navigator.clipboard.writeText(canon);
      toast.success(`Identifiant « ${canon} » copié`);
    } catch (e) {
      toast.error("Copie refusée");
    }
  }

  async function clearTestDetections() {
    const dry = await api.post("/livre/ble/debug/clear-detections",
      { dry_run: true, only_test: true }).then(r => r.data);
    if (!dry.detections_to_delete) {
      toast.info("Aucune détection de test à supprimer");
      return;
    }
    if (!window.confirm(
      `Supprimer ${dry.detections_to_delete} détection(s) de TEST ?\n\n` +
      `(simulator OR identifiant TEST/CONFLICTAG/MOCK)\n` +
      `Les détections réelles seront préservées.`
    )) return;
    try {
      const { data } = await api.post("/livre/ble/debug/clear-detections",
        { dry_run: false, only_test: true });
      toast.success(`${data.detections_deleted} détection(s) supprimée(s)`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  async function clearAllDetections() {
    const dry = await api.post("/livre/ble/debug/clear-detections",
      { dry_run: true, only_test: false }).then(r => r.data);
    if (!window.confirm(
      `Supprimer TOUTES les détections BLE ?\n\n` +
      `${dry.detections_to_delete} détection(s) (test + réelles) seront effacées.\n` +
      `Action IRRÉVERSIBLE.`
    )) return;
    try {
      const { data } = await api.post("/livre/ble/debug/clear-detections",
        { dry_run: false, only_test: false });
      toast.success(`${data.detections_deleted} détection(s) supprimée(s)`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl" data-testid="ble-debug-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bug className="w-5 h-5 text-amber-500" /> Debug BLE
            <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
              <Radio className={`w-2.5 h-2.5 ${auto ? "animate-pulse" : ""}`} />
              {auto ? "Live · 3 s" : "Pause"}
            </span>
          </DialogTitle>
          <DialogDescription>
            Liste des dernières détections BLE remontées par la PWA chauffeur et l&apos;app native.
            Cliquez « Copier » pour récupérer l&apos;identifiant canonique à coller dans
            « Gérer les tags BLE ».
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between gap-2 mb-1">
          <p className="text-xs text-slate-500">
            {rows.length > 0 ? `${rows.length} détection(s) — la plus récente en premier` : "Aucune détection récente"}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={clearTestDetections}
                    data-testid="ble-debug-clear-test"
                    className="h-8 text-xs text-amber-700 border-amber-300 hover:bg-amber-50"
                    title="Supprime uniquement les détections simulator + TEST/CONFLICTAG/MOCK">
              <Eraser className="w-3 h-3 mr-1" /> Vider tests
            </Button>
            <Button variant="outline" size="sm" onClick={clearAllDetections}
                    data-testid="ble-debug-clear-all"
                    className="h-8 text-xs text-rose-700 border-rose-300 hover:bg-rose-50"
                    title="Supprime TOUTES les détections (irréversible)">
              <Eraser className="w-3 h-3 mr-1" /> Tout vider
            </Button>
            <Button variant="outline" size="sm" onClick={() => setAuto(!auto)}
                    data-testid="ble-debug-toggle-auto" className="h-8 text-xs">
              {auto ? "Pause" : "Reprendre"}
            </Button>
            <Button variant="outline" size="sm" onClick={load} disabled={loading}
                    data-testid="ble-debug-refresh" className="h-8 text-xs">
              {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            </Button>
          </div>
        </div>

        <div className="border border-slate-200 rounded-md overflow-auto max-h-[420px]"
             data-testid="ble-debug-scroll">
          <table className="w-full text-xs min-w-[900px]">
            <thead className="bg-slate-50 sticky top-0 z-10">
              <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Heure</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Nom local</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Identifiant brut</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Canonique</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Device ID</th>
                <th className="text-right px-2 py-2 font-medium whitespace-nowrap">RSSI</th>
                <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Moy.</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Plateforme</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Chauffeur</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Manuf. data</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">UUIDs</th>
                <th className="text-left px-2 py-2 font-medium whitespace-nowrap">Tag</th>
                <th className="text-right px-2 py-2 font-medium whitespace-nowrap">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={13} className="py-8 text-center text-slate-400">
                  En attente de détections…
                </td></tr>
              )}
              {rows.map((r, i) => (
                <tr key={`${r.ts}-${i}`}
                    data-testid={`ble-debug-row-${i}`}
                    className={`border-t border-slate-100 hover:bg-slate-50/50 ${r.matched_tag_id ? "" : "bg-amber-50/20"}`}>
                  <td className="px-2 py-1.5 text-slate-500 font-mono whitespace-nowrap">
                    {r.ts ? new Date(r.ts).toLocaleTimeString("fr-FR") : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-slate-700 whitespace-nowrap">
                    {r.local_name || "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-slate-800 whitespace-nowrap">
                    {r.identifier_raw || "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-[#2196F3] whitespace-nowrap">
                    {r.identifier_canon || "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-slate-500 whitespace-nowrap">
                    {r.device_id || "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right text-slate-700 whitespace-nowrap">
                    {r.rssi ?? "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right text-slate-500 whitespace-nowrap">
                    {r.rssi_avg ?? "—"}
                  </td>
                  <td className="px-2 py-1.5 text-slate-600 whitespace-nowrap">
                    {r.platform || "—"}
                  </td>
                  <td className="px-2 py-1.5 text-slate-700 whitespace-nowrap">
                    {r.driver_name}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-slate-500 whitespace-nowrap">
                    {r.manufacturer_data || "—"}
                  </td>
                  <td className="px-2 py-1.5 font-mono text-slate-500 whitespace-nowrap">
                    {Array.isArray(r.service_uuids) ? r.service_uuids.join(", ") : (r.service_uuids || "—")}
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    {r.matched_tag_id
                      ? <span className="text-emerald-600">✓ associé</span>
                      : <span className="text-amber-600">non associé</span>}
                  </td>
                  <td className="px-2 py-1.5 text-right whitespace-nowrap">
                    <Button
                      size="sm" variant="ghost"
                      onClick={() => copyCanon(r.identifier_canon)}
                      disabled={!r.identifier_canon}
                      className="h-6 text-[10px] px-2"
                      data-testid={`ble-debug-copy-${i}`}
                    >
                      <Copy className="w-3 h-3 mr-1" /> Copier
                    </Button>
                    {!r.matched_tag_id && r.identifier_canon && (
                      <Button
                        size="sm" variant="ghost"
                        onClick={() => { setPairTarget({ canon: r.identifier_canon, raw: r.identifier_raw }); setPairOpen(true); }}
                        className="h-6 text-[10px] px-2 ml-1 text-[#2196F3]"
                        data-testid={`ble-debug-pair-${i}`}
                      >
                        <LinkIcon className="w-3 h-3 mr-1" /> Apparier
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="ble-debug-close">
            Fermer
          </Button>
        </DialogFooter>
        <PairAliasDialog
          open={pairOpen}
          onOpenChange={setPairOpen}
          aliasCanon={pairTarget?.canon}
          aliasRaw={pairTarget?.raw}
          onDone={load}
        />
      </DialogContent>
    </Dialog>
  );
}
