import { useCallback, useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import {
  Smartphone, Bluetooth, Loader2, KeyRound, Copy, ShieldOff, ShieldCheck,
  Truck, History, ListChecks, Clock, XCircle,
} from "lucide-react";
import { SourceBadge } from "@/components/livre/SourceBadge";

const STATUS_LABEL = {
  open: "Ouverte", automatic: "Automatique", confirmed: "Confirmé",
  pending: "À valider", manual: "Manuel", conflict: "Conflit",
  closed: "Clôturée", cancelled: "Annulée", ending: "En clôture",
};

const EVENT_LABEL = {
  driver_claim: "Confirmation APP « Je conduis »",
  driver_change: "Changement de chauffeur",
  driver_session_closed: "Session clôturée",
  amend_session: "Correction admin",
  resolve_conflict: "Conflit résolu",
  "auth.login": "Connexion",
  "driver.password_reset": "Mot de passe réinitialisé",
  "driver.ble_tag_assigned": "Tag BLE associé",
  "driver.ble_tag_removed": "Tag BLE retiré",
  "driver.grant_access": "Accès mobile créé",
  "driver.disabled": "Chauffeur désactivé",
  "driver.enabled": "Chauffeur réactivé",
  "driver.create": "Chauffeur créé",
  "driver.update": "Fiche modifiée",
};

function fmt(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-CH", { dateStyle: "short", timeStyle: "short" }); }
  catch { return iso; }
}

function duration(startIso, endIso) {
  if (!startIso) return "—";
  const end = endIso ? new Date(endIso) : new Date();
  const mins = Math.max(0, Math.round((end - new Date(startIso)) / 60000));
  if (mins < 60) return `${mins} min`;
  return `${Math.floor(mins / 60)} h ${String(mins % 60).padStart(2, "0")}`;
}

function Row({ label, value, testId }) {
  return (
    <div className="flex justify-between gap-3 text-sm py-1">
      <span className="text-slate-500 text-xs uppercase tracking-wider pt-0.5">{label}</span>
      <span className="text-slate-800 text-right font-medium" data-testid={testId}>{value ?? "—"}</span>
    </div>
  );
}

export default function DriverSheet({ driverId, open, onOpenChange, onChanged }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tempPw, setTempPw] = useState(null);
  const [tagEdit, setTagEdit] = useState(null); // null | string being edited
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!driverId) return;
    setLoading(true);
    try {
      const { data: d } = await api.get(`/livre/team/drivers/${driverId}/overview`);
      setData(d);
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setLoading(false); }
  }, [driverId]);

  useEffect(() => {
    if (open) { setTempPw(null); setTagEdit(null); load(); }
  }, [open, load]);

  async function resetPassword() {
    if (!window.confirm(`Réinitialiser le mot de passe de ${data.driver.name} ?\nUn mot de passe temporaire sera généré et affiché UNE SEULE FOIS.`)) return;
    setBusy(true);
    try {
      const { data: r } = await api.post(`/livre/team/drivers/${driverId}/reset-password`);
      setTempPw(r.temp_password);
      toast.success("Mot de passe temporaire généré — copiez-le maintenant");
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function toggleAccount(active) {
    setBusy(true);
    try {
      await api.patch(`/livre/team/users/${data.account.user_id}`, { active });
      toast.success(active ? "Accès réactivé" : "Accès désactivé");
      load(); onChanged?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function saveTag(value) {
    setBusy(true);
    try {
      await api.patch(`/livre/team/drivers/${driverId}`, { ble_id: value || null });
      toast.success(value ? "Tag BLE associé" : "Tag BLE retiré");
      setTagEdit(null);
      load(); onChanged?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  async function closeSession() {
    const s = data.current_session;
    if (!window.confirm(`Clôturer la session en cours sur ${s.vehicle_plate || s.vehicle_id} ?`)) return;
    setBusy(true);
    try {
      await api.put(`/livre/ble/sessions/${s.id}`, { status: "closed" });
      toast.success("Session clôturée (action auditée)");
      load(); onChanged?.();
    } catch (e) { toast.error(formatApiErrorDetail(e.response?.data?.detail)); }
    finally { setBusy(false); }
  }

  const d = data?.driver;
  const acc = data?.account;
  const ident = data?.identification;
  const cur = data?.current_session;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-xl overflow-y-auto" data-testid="driver-sheet">
        {loading || !data ? (
          <div className="py-20 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-slate-400" /></div>
        ) : (
          <>
            <SheetHeader>
              <SheetTitle className="flex items-center gap-2.5" data-testid="driver-sheet-title">
                {d.name}
                <Badge variant="outline" className={d.active !== false
                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : "bg-slate-100 text-slate-500 border-slate-300"}>
                  {d.active !== false ? "Actif" : "Inactif"}
                </Badge>
              </SheetTitle>
              {data.last_activity && (
                <p className="text-xs text-slate-500 flex items-center gap-1.5" data-testid="driver-sheet-last-activity">
                  <Clock className="w-3 h-3" /> Dernière activité : {fmt(data.last_activity.ts)} — {data.last_activity.kind}
                </p>
              )}
            </SheetHeader>

            <div className="space-y-5 mt-4 pb-8">
              {/* A. Identité */}
              <section data-testid="driver-sheet-identity">
                <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-1">Identité</p>
                <div className="rounded-md border border-slate-200 px-3 py-2 bg-white">
                  <Row label="Prénom" value={d.first_name} />
                  <Row label="Nom" value={d.last_name || (!d.first_name ? d.name : null)} />
                  <Row label="E-mail" value={d.email} />
                  <Row label="Téléphone" value={d.phone} />
                  <Row label="Matricule" value={d.internal_number} />
                  <Row label="Créé le" value={fmt(d.created_at)} />
                </div>
              </section>

              {/* B. Compte mobile */}
              <section data-testid="driver-sheet-account">
                <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-1">Compte mobile</p>
                <div className="rounded-md border border-slate-200 px-3 py-2 bg-white space-y-1">
                  {!acc ? (
                    <p className="text-sm text-slate-400 py-1">Aucun compte mobile — utilisez « Activer l'accès » depuis la liste.</p>
                  ) : (
                    <>
                      <Row label="Statut" value={
                        <Badge variant="outline" className={acc.active
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : "bg-rose-50 text-rose-700 border-rose-200"}>
                          {acc.active ? "Actif" : "Désactivé"}
                        </Badge>} testId="driver-sheet-account-status" />
                      <Row label="E-mail" value={acc.email} />
                      <Row label="Dernière connexion" value={fmt(acc.last_login_at)} testId="driver-sheet-last-login" />
                      {acc.must_change_password && (
                        <p className="text-[11px] text-amber-600">Changement de mot de passe requis à la prochaine connexion</p>
                      )}
                      {tempPw && (
                        <div className="rounded-md border border-amber-300 bg-amber-50 p-2.5 space-y-1.5" data-testid="driver-temp-password">
                          <p className="text-[11px] font-semibold text-amber-800">
                            Mot de passe temporaire — affiché une seule fois, non relisible :
                          </p>
                          <div className="flex items-center gap-1.5">
                            <Input readOnly value={tempPw} className="h-8 font-mono text-sm bg-white"
                                   onFocus={(e) => e.target.select()} data-testid="driver-temp-password-value" />
                            <Button size="sm" variant="outline" className="h-8 shrink-0"
                                    onClick={() => navigator.clipboard.writeText(tempPw).then(() => toast.success("Copié"))}>
                              <Copy className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        </div>
                      )}
                      <div className="flex gap-2 pt-1.5 flex-wrap">
                        <Button size="sm" variant="outline" className="h-7 text-xs" disabled={busy}
                                onClick={resetPassword} data-testid="driver-sheet-reset-password">
                          <KeyRound className="w-3.5 h-3.5 mr-1" /> Réinitialiser mot de passe
                        </Button>
                        {acc.active ? (
                          <Button size="sm" variant="outline" className="h-7 text-xs text-rose-600 border-rose-200"
                                  disabled={busy} onClick={() => toggleAccount(false)}
                                  data-testid="driver-sheet-disable-access">
                            <ShieldOff className="w-3.5 h-3.5 mr-1" /> Désactiver l'accès
                          </Button>
                        ) : (
                          <Button size="sm" variant="outline" className="h-7 text-xs text-emerald-600 border-emerald-200"
                                  disabled={busy} onClick={() => toggleAccount(true)}
                                  data-testid="driver-sheet-enable-access">
                            <ShieldCheck className="w-3.5 h-3.5 mr-1" /> Réactiver l'accès
                          </Button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </section>

              {/* C. Méthodes d'identification */}
              <section data-testid="driver-sheet-identification">
                <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-1">Méthodes d'identification</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div className="rounded-md border border-slate-200 p-3 bg-white">
                    <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5 mb-1.5">
                      <Smartphone className="w-3.5 h-3.5 text-blue-500" /> Application mobile
                      {ident.app.enabled
                        ? <Badge variant="outline" className="bg-emerald-50 text-emerald-700 border-emerald-200 text-[10px]">Active</Badge>
                        : <Badge variant="outline" className="bg-slate-100 text-slate-500 border-slate-200 text-[10px]">Non configurée</Badge>}
                    </p>
                    <p className="text-[11px] text-slate-500">Dernière connexion : <span className="text-slate-700">{fmt(ident.app.last_login_at)}</span></p>
                    <p className="text-[11px] text-slate-500">Dernière confirmation : <span className="text-slate-700">{fmt(ident.app.last_claim_at)}</span></p>
                  </div>
                  <div className="rounded-md border border-slate-200 p-3 bg-white">
                    <p className="text-xs font-semibold text-slate-700 flex items-center gap-1.5 mb-1.5">
                      <Bluetooth className="w-3.5 h-3.5 text-cyan-500" /> Bluetooth
                      {ident.ble.tag
                        ? <Badge variant="outline" className="bg-cyan-50 text-cyan-700 border-cyan-200 text-[10px]">Tag associé</Badge>
                        : <Badge variant="outline" className="bg-slate-100 text-slate-500 border-slate-200 text-[10px]">Aucun tag</Badge>}
                    </p>
                    <p className="text-[11px] text-slate-500">Tag : <span className="font-mono text-slate-700" data-testid="driver-sheet-ble-tag">{ident.ble.tag || "—"}</span></p>
                    <p className="text-[11px] text-slate-500">Dernière détection : <span className="text-slate-700">{fmt(ident.ble.last_detection_at)}</span></p>
                    {ident.ble.field_validation_note && (
                      <p className="text-[10px] text-amber-600 mt-1" data-testid="driver-sheet-ble-pending">
                        Validation terrain : en attente
                      </p>
                    )}
                    {tagEdit === null ? (
                      <div className="flex gap-1.5 mt-2">
                        <Button size="sm" variant="outline" className="h-6 text-[11px] px-2"
                                onClick={() => setTagEdit(ident.ble.tag || "")}
                                data-testid="driver-sheet-tag-edit">
                          {ident.ble.tag ? "Remplacer" : "Associer un tag"}
                        </Button>
                        {ident.ble.tag && (
                          <Button size="sm" variant="outline" className="h-6 text-[11px] px-2 text-rose-600 border-rose-200"
                                  disabled={busy} onClick={() => saveTag(null)}
                                  data-testid="driver-sheet-tag-remove">
                            Retirer
                          </Button>
                        )}
                      </div>
                    ) : (
                      <div className="flex gap-1.5 mt-2">
                        <Input value={tagEdit} onChange={(e) => setTagEdit(e.target.value)}
                               placeholder="A4:C1:38:XX:XX:22" className="h-7 text-xs font-mono"
                               data-testid="driver-sheet-tag-input" />
                        <Button size="sm" className="h-7 text-[11px] px-2" disabled={busy || !tagEdit.trim()}
                                onClick={() => saveTag(tagEdit.trim())} data-testid="driver-sheet-tag-save">OK</Button>
                        <Button size="sm" variant="ghost" className="h-7 text-[11px] px-2"
                                onClick={() => setTagEdit(null)}>✕</Button>
                      </div>
                    )}
                  </div>
                </div>
              </section>

              {/* D. Session actuelle */}
              <section data-testid="driver-sheet-current-session">
                <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-1">Session actuelle</p>
                <div className="rounded-md border border-slate-200 px-3 py-2 bg-white">
                  {!cur ? (
                    <p className="text-sm text-slate-400 py-1">Aucune session en cours</p>
                  ) : (
                    <>
                      <Row label="Véhicule" value={<span className="font-mono">{cur.vehicle_plate || cur.vehicle_id}</span>}
                           testId="driver-sheet-session-vehicle" />
                      <Row label="Début" value={fmt(cur.started_at)} />
                      <Row label="Durée" value={duration(cur.started_at)} />
                      <Row label="Identification" value={<SourceBadge source={cur.identification_source} />} />
                      <Row label="Statut" value={STATUS_LABEL[cur.status] || cur.status} />
                      <div className="pt-1.5">
                        <Button size="sm" variant="outline" className="h-7 text-xs text-rose-600 border-rose-200"
                                disabled={busy} onClick={closeSession} data-testid="driver-sheet-close-session">
                          <XCircle className="w-3.5 h-3.5 mr-1" /> Clôturer la session
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              </section>

              <Separator />

              {/* E. Historique des sessions */}
              <section data-testid="driver-sheet-sessions">
                <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-1 flex items-center gap-1.5">
                  <History className="w-3 h-3" /> Dernières sessions ({data.sessions.length})
                </p>
                {data.sessions.length === 0 ? (
                  <p className="text-sm text-slate-400">Aucune session enregistrée</p>
                ) : (
                  <div className="rounded-md border border-slate-200 overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-slate-50 text-slate-500 text-[10px] uppercase tracking-wider">
                          <th className="text-left px-2.5 py-1.5">Date</th>
                          <th className="text-left px-2.5 py-1.5">Véhicule</th>
                          <th className="text-left px-2.5 py-1.5">Durée</th>
                          <th className="text-left px-2.5 py-1.5">Source</th>
                          <th className="text-left px-2.5 py-1.5">Statut</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.sessions.map((s) => (
                          <tr key={s.id} className="border-t border-slate-100" data-testid={`driver-sheet-session-${s.id}`}>
                            <td className="px-2.5 py-1.5 font-mono text-slate-600">{fmt(s.started_at)}</td>
                            <td className="px-2.5 py-1.5 font-mono">{s.vehicle_plate || "—"}</td>
                            <td className="px-2.5 py-1.5">{duration(s.started_at, s.ended_at)}</td>
                            <td className="px-2.5 py-1.5"><SourceBadge source={s.identification_source} /></td>
                            <td className="px-2.5 py-1.5 text-slate-600">{STATUS_LABEL[s.status] || s.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              {/* F. Historique d'identification */}
              <section data-testid="driver-sheet-events">
                <p className="text-[10px] uppercase tracking-[0.15em] text-slate-400 font-semibold mb-1 flex items-center gap-1.5">
                  <ListChecks className="w-3 h-3" /> Historique d'identification
                </p>
                {data.events.length === 0 ? (
                  <p className="text-sm text-slate-400">Aucun événement</p>
                ) : (
                  <ul className="space-y-1">
                    {data.events.map((e, i) => (
                      <li key={i} className="text-xs flex gap-2 items-baseline" data-testid={`driver-sheet-event-${i}`}>
                        <span className="font-mono text-slate-400 shrink-0">{fmt(e.event_ts)}</span>
                        <span className="text-slate-700">{EVENT_LABEL[e.action] || e.action}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
