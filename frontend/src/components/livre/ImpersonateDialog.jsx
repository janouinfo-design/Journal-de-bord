import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Eye } from "lucide-react";

export default function ImpersonateDialog({ target, onOpenChange, onConfirm }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await onConfirm(reason.trim());
      setReason("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={!!target} onOpenChange={(o) => { if (!o) { setReason(""); onOpenChange(null); } }}>
      <DialogContent data-testid="impersonate-dialog" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Eye className="w-5 h-5" /> Se connecter comme…
          </DialogTitle>
          <DialogDescription>
            Ouvre l'application comme <strong>{target?.name || target?.email}</strong> dans un
            nouvel onglet. Votre session administrateur reste intacte et chaque action sera
            tracée dans le journal d'audit.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5 py-1">
          <Label>Motif (facultatif)</Label>
          <Input data-testid="impersonate-reason" value={reason}
                 placeholder="Ex. ticket support #123, vérification des accès…"
                 onChange={(e) => setReason(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(null)}>Annuler</Button>
          <Button data-testid="impersonate-confirm" onClick={confirm} disabled={busy}>
            {busy ? "Ouverture…" : "Ouvrir l'aperçu"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
