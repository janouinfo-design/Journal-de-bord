import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, formatApiErrorDetail, fmtDateTime } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { STATEMENT_STATUS, fmtAmount } from "@/lib/fuelLabels";
import { Plus, AlertTriangle } from "lucide-react";

function defaultMonth() {
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function FuelStatementsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const [rows, setRows] = useState([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ mode: "month", period_month: defaultMonth(), date_from: "", date_to: "", type: "regular" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api.get("/livre/fuel/statements").then(({ data }) => setRows(data))
      .catch((e) => toast.error(formatApiErrorDetail(e.response?.data?.detail)));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function create() {
    setSaving(true);
    try {
      const payload = form.mode === "month"
        ? { period_month: form.period_month, type: form.type }
        : { date_from: form.date_from, date_to: form.date_to, type: form.type };
      const { data } = await api.post("/livre/fuel/statements", payload);
      toast.success(`Décompte ${data.number} créé (brouillon)`);
      setCreateOpen(false);
      navigate(`/livre/carburant/decomptes/${data.id}`);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setSaving(false); }
  }

  const valid = form.mode === "month" ? !!form.period_month : (form.date_from && form.date_to);

  return (
    <div data-testid="fuel-statements-page" className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500 max-w-2xl">
          Un décompte regroupe les transactions d'une période (date comptable fournisseur, sinon date de
          transaction). La clôture fige montants, taux et affectations — définitivement.
        </p>
        {isAdmin && (
          <Button data-testid="fuel-stmt-create-btn" onClick={() => setCreateOpen(true)}
                  className="bg-[#2196F3] hover:bg-[#1976D2] text-white h-9 shrink-0">
            <Plus className="w-4 h-4 mr-1.5" /> Nouveau décompte
          </Button>
        )}
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400">
              <th className="px-4 py-3">Numéro</th><th className="px-4 py-3">Période</th>
              <th className="px-4 py-3">Type</th><th className="px-4 py-3">Version</th>
              <th className="px-4 py-3">Transactions</th><th className="px-4 py-3">Total CHF</th>
              <th className="px-4 py-3">À contrôler</th><th className="px-4 py-3">Statut</th>
              <th className="px-4 py-3">Créé le</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-400">
                Aucun décompte — créez le premier
              </td></tr>
            ) : rows.map((s) => {
              const st = STATEMENT_STATUS[s.status] || STATEMENT_STATUS.draft;
              const sum = s.totals_summary || {};
              return (
                <tr key={s.id} data-testid={`fuel-stmt-row-${s.id}`}
                    className="border-b border-slate-100 hover:bg-slate-50/60 cursor-pointer"
                    onClick={() => navigate(`/livre/carburant/decomptes/${s.id}`)}>
                  <td className="px-4 py-2.5 text-xs font-mono font-medium">{s.number}</td>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{s.date_from} → {s.date_to}</td>
                  <td className="px-4 py-2.5 text-xs">{s.type === "corrective" ? "Correctif" : "Régulier"}</td>
                  <td className="px-4 py-2.5 text-xs">V{s.version}{(s.versions || []).length > 0 && (
                    <span className="text-amber-600 ml-1" title="Versions précédentes remplacées">↺</span>)}</td>
                  <td className="px-4 py-2.5 text-xs">{sum.tx_count ?? "—"}</td>
                  <td className="px-4 py-2.5 text-xs font-medium">{sum.amount_chf_total != null ? fmtAmount(sum.amount_chf_total) : "—"}</td>
                  <td className="px-4 py-2.5 text-xs">
                    {sum.blockers_count > 0
                      ? <span className="inline-flex items-center gap-1 text-amber-600 font-semibold">
                          <AlertTriangle className="w-3 h-3" />{sum.blockers_count}</span>
                      : "0"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex px-2 py-0.5 rounded-full border text-[11px] font-medium ${st.cls}`}>{st.label}</span>
                  </td>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{fmtDateTime(s.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog open={createOpen} onOpenChange={(o) => !o && setCreateOpen(false)}>
        <DialogContent data-testid="fuel-stmt-create-dialog" className="max-w-md">
          <DialogHeader><DialogTitle>Nouveau décompte carburant</DialogTitle></DialogHeader>
          <div className="space-y-3 py-1">
            <div className="space-y-1.5">
              <Label>Période</Label>
              <Select value={form.mode} onValueChange={(v) => setForm({ ...form, mode: v })}>
                <SelectTrigger data-testid="fuel-stmt-period-mode"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="month">Mensuelle (recommandé)</SelectItem>
                  <SelectItem value="custom">Personnalisée (contrôles / correctifs)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.mode === "month" ? (
              <div className="space-y-1.5">
                <Label>Mois</Label>
                <Input data-testid="fuel-stmt-month" type="month" value={form.period_month}
                       onChange={(e) => setForm({ ...form, period_month: e.target.value })} />
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label>Du</Label>
                  <Input data-testid="fuel-stmt-from" type="date" value={form.date_from}
                         onChange={(e) => setForm({ ...form, date_from: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>Au</Label>
                  <Input data-testid="fuel-stmt-to" type="date" value={form.date_to}
                         onChange={(e) => setForm({ ...form, date_to: e.target.value })} />
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              <Label>Type</Label>
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger data-testid="fuel-stmt-type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="regular">Régulier</SelectItem>
                  <SelectItem value="corrective">Correctif (transactions tardives / corrections)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <p className="text-[10px] text-slate-400">
              Les transactions antérieures non encore clôturées (reportées/tardives) sont automatiquement
              incluses dans une section séparée. Période déterminée en fuseau Europe/Zurich.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Annuler</Button>
            <Button data-testid="fuel-stmt-create-save" onClick={create} disabled={saving || !valid}>
              {saving ? "Génération…" : "Générer le brouillon"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
