import { useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
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
import { PRODUCT_LABEL } from "@/lib/fuelLabels";

const EMPTY = {
  card_id: "", tx_datetime: "", station_name: "", country: "CH",
  product_type: "", quantity: "", unit: "L", unit_price: "", amount_total: "",
  currency: "CHF", mileage: "", vehicle_id: "", driver_id: "",
  invoice_ref: "", comment: "", reason: "",
};

export default function ManualTxDialog({ open, onClose, refs, onCreated }) {
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [dupWarning, setDupWarning] = useState(false);

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));
  const setInput = (k) => (e) => set(k)(e.target.value);

  async function save(force = false) {
    setSaving(true);
    try {
      await api.post("/livre/fuel/transactions", {
        card_id: form.card_id || null,
        tx_datetime: new Date(form.tx_datetime).toISOString(),
        station_name: form.station_name || null,
        country: form.country || null,
        product_type: form.product_type || null,
        quantity: form.quantity === "" ? null : Number(form.quantity),
        unit: form.unit,
        unit_price: form.unit_price === "" ? null : Number(form.unit_price),
        amount_total: Number(form.amount_total),
        currency: form.currency,
        mileage: form.mileage === "" ? null : Number(form.mileage),
        vehicle_id: form.vehicle_id || null,
        driver_id: form.driver_id || null,
        invoice_ref: form.invoice_ref || null,
        comment: form.comment || null,
        reason: form.reason,
        force,
      });
      toast.success("Transaction créée");
      setForm(EMPTY); setDupWarning(false);
      onCreated?.(); onClose();
    } catch (e) {
      if (e.response?.status === 409) setDupWarning(true);
      else toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally { setSaving(false); }
  }

  const valid = form.tx_datetime && form.amount_total !== "" && form.reason.trim();

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="fuel-manual-tx-dialog" className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>Nouvelle transaction (saisie manuelle)</DialogTitle></DialogHeader>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 py-1">
          <div className="space-y-1.5">
            <Label>Date et heure *</Label>
            <Input data-testid="fuel-manual-datetime" type="datetime-local" value={form.tx_datetime}
                   onChange={setInput("tx_datetime")} />
          </div>
          <div className="space-y-1.5">
            <Label>Carte</Label>
            <Select value={form.card_id || "none"} onValueChange={(v) => set("card_id")(v === "none" ? "" : v)}>
              <SelectTrigger data-testid="fuel-manual-card"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Aucune (paiement hors carte)</SelectItem>
                {(refs.cards || []).map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.provider} •••• {c.last4}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Station</Label>
            <Input data-testid="fuel-manual-station" value={form.station_name} onChange={setInput("station_name")} />
          </div>
          <div className="space-y-1.5">
            <Label>Pays</Label>
            <Input value={form.country} maxLength={2} onChange={setInput("country")} />
          </div>
          <div className="space-y-1.5">
            <Label>Produit</Label>
            <Select value={form.product_type || "none"} onValueChange={(v) => set("product_type")(v === "none" ? "" : v)}>
              <SelectTrigger data-testid="fuel-manual-product"><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">—</SelectItem>
                {(refs.product_types || []).map((p) => <SelectItem key={p} value={p}>{PRODUCT_LABEL[p] || p}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label>Quantité</Label>
              <Input type="number" value={form.quantity} onChange={setInput("quantity")} />
            </div>
            <div className="space-y-1.5">
              <Label>Unité</Label>
              <Select value={form.unit} onValueChange={set("unit")}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="L">Litres</SelectItem>
                  <SelectItem value="kWh">kWh</SelectItem>
                  <SelectItem value="unit">Unité</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Prix unitaire</Label>
            <Input type="number" value={form.unit_price} onChange={setInput("unit_price")} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label>Montant TTC *</Label>
              <Input data-testid="fuel-manual-amount" type="number" value={form.amount_total} onChange={setInput("amount_total")} />
            </div>
            <div className="space-y-1.5">
              <Label>Devise</Label>
              <Input value={form.currency} maxLength={3} onChange={setInput("currency")} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Véhicule</Label>
            <Select value={form.vehicle_id || "none"} onValueChange={(v) => set("vehicle_id")(v === "none" ? "" : v)}>
              <SelectTrigger data-testid="fuel-manual-vehicle"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Rapprochement automatique</SelectItem>
                {(refs.vehicles || []).map((v) => <SelectItem key={v.id} value={v.id}>{v.plate}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Chauffeur</Label>
            <Select value={form.driver_id || "none"} onValueChange={(v) => set("driver_id")(v === "none" ? "" : v)}>
              <SelectTrigger data-testid="fuel-manual-driver"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">—</SelectItem>
                {(refs.drivers || []).map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Kilométrage</Label>
            <Input type="number" value={form.mileage} onChange={setInput("mileage")} />
          </div>
          <div className="space-y-1.5">
            <Label>N° facture / relevé</Label>
            <Input value={form.invoice_ref} onChange={setInput("invoice_ref")} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Commentaire</Label>
            <Input value={form.comment} onChange={setInput("comment")} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label>Motif de la saisie manuelle *</Label>
            <Input data-testid="fuel-manual-reason" placeholder="Ex. : plein payé en espèces, relevé fournisseur incomplet…"
                   value={form.reason} onChange={setInput("reason")} />
          </div>
        </div>
        {dupWarning && (
          <div data-testid="fuel-manual-dup-warning"
               className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-700">
            Doublon probable détecté (même carte, date, station, montant). Confirmez uniquement s'il s'agit
            bien d'une transaction distincte.
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          {dupWarning ? (
            <Button data-testid="fuel-manual-force" className="bg-amber-600 hover:bg-amber-700 text-white"
                    onClick={() => save(true)} disabled={saving}>Confirmer malgré le doublon</Button>
          ) : (
            <Button data-testid="fuel-manual-save" onClick={() => save(false)} disabled={saving || !valid}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
