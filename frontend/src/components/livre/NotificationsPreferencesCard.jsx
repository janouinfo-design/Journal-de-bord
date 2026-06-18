import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  Bell, Loader2, Mail, MessageSquare, Smartphone, Send, Save, RefreshCw,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

/**
 * Notification preferences panel.
 *
 * - Lists the event catalog (GET /livre/notifications/catalog)
 * - Loads / persists per-user preferences (GET/PUT /livre/notifications/preferences)
 * - Master switches for the 3 channels (push/email/sms) — apply on top of per-event toggles
 * - Per-event 3-channel matrix
 * - Admin-only "Tester notification" button → POST /livre/notifications/test
 *
 * RBAC:
 *  - Any authenticated user can manage their OWN preferences.
 *  - Admin only can switch to other users' preferences (via the user selector) and
 *    can run the test endpoint.
 */
export default function NotificationsPreferencesCard() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [catalog, setCatalog] = useState([]);
  const [prefs, setPrefs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(null); // event being tested
  const [error, setError] = useState(null);

  // Admin can also see/edit a different user's preferences. Default = self.
  const [users, setUsers] = useState([]); // admin only — list of registered users (best-effort)
  const [targetUserId, setTargetUserId] = useState(user?.id || null);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [cat, pr] = await Promise.all([
          api.get("/livre/notifications/catalog").then((r) => r.data?.events || []),
          api.get("/livre/notifications/preferences").then((r) => r.data),
        ]);
        if (!alive) return;
        setCatalog(cat);
        setPrefs(pr);
      } catch (e) {
        if (!alive) return;
        setError(e?.response?.data?.detail || "Impossible de charger les notifications");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  // Admin-only: best-effort user list for the "Other user" selector.
  // We derive it from drivers + the current user — there is no public
  // /api/users endpoint yet, so this stays defensive.
  useEffect(() => {
    if (!isAdmin) return;
    api.get("/livre/drivers").then((r) => {
      const drivers = r.data || [];
      const acc = [{ id: user.id, label: `${user.email} (vous)` }];
      for (const d of drivers) {
        if (d.email && d.email !== user.email) {
          acc.push({ id: d.id, label: `${d.name || d.email} (${d.email})` });
        }
      }
      setUsers(acc);
    }).catch(() => { /* ignore */ });
  }, [isAdmin, user]);

  function togglePref(eventName, channel, value) {
    setPrefs((prev) => {
      if (!prev) return prev;
      const next = {
        ...prev,
        events: {
          ...prev.events,
          [eventName]: {
            ...(prev.events[eventName] || {}),
            [channel]: value,
          },
        },
      };
      return next;
    });
  }

  function toggleMasterChannel(channel, value) {
    setPrefs((prev) => prev && ({
      ...prev,
      channels: { ...prev.channels, [channel]: value },
    }));
  }

  async function save() {
    if (!prefs) return;
    setSaving(true);
    setError(null);
    try {
      const { data } = await api.put("/livre/notifications/preferences", {
        channels: prefs.channels,
        events: prefs.events,
      });
      setPrefs(data);
      toast.success("Préférences enregistrées");
    } catch (e) {
      const msg = e?.response?.data?.detail || "Sauvegarde refusée";
      setError(msg);
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  }

  async function testEvent(eventName) {
    setTesting(eventName);
    try {
      const { data } = await api.post("/livre/notifications/test", {
        event: eventName,
        user_ids: [targetUserId],
        payload: { vehicle_plate: "TEST-99", session_id: "test", drivers: [] },
      });
      const sent = data?.push?.sent ?? 0;
      const failed = data?.push?.failed ?? 0;
      if (sent > 0) {
        toast.success(`Notification envoyée à ${sent} appareil(s)`);
      } else if (failed > 0) {
        toast.warning(`${failed} échec(s) d'envoi — tokens probablement invalides`);
      } else {
        toast.info("Aucun appareil enregistré pour cette cible.");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Échec du test");
    } finally {
      setTesting(null);
    }
  }

  const grouped = useMemo(() => {
    if (!catalog.length) return { core: [], business: [] };
    const core = catalog.filter((e) => e.event.startsWith("ble.") || e.event === "kill_switch");
    const business = catalog.filter((e) => !core.includes(e));
    return { core, business };
  }, [catalog]);

  if (loading) {
    return (
      <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-8 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-[#2196F3]" />
      </Card>
    );
  }

  if (error && !prefs) {
    return (
      <Card className="bg-white border-rose-200 shadow-sm rounded-lg p-5"
            data-testid="settings-notifications-error">
        <p className="text-sm text-rose-700">{error}</p>
      </Card>
    );
  }

  return (
    <Card className="bg-white border-slate-200 shadow-sm rounded-lg p-5"
          data-testid="settings-notifications-card">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div className="flex items-start gap-3">
          <span className="shrink-0 w-7 h-7 rounded-full bg-[#2196F3] text-white text-xs font-semibold flex items-center justify-center mt-0.5">
            5
          </span>
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
              <Bell className="w-4 h-4 text-[#2196F3]" /> Préférences de notification
            </h2>
            <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
              Choisissez quels événements vous recevez et sur quels canaux (push, e-mail, SMS).
            </p>
          </div>
        </div>
        <Button
          onClick={save}
          disabled={saving || !prefs}
          className="bg-[#2196F3] hover:bg-[#1E88E5] text-white shadow-sm"
          data-testid="settings-notifications-save"
        >
          {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Save className="w-4 h-4 mr-2" />}
          Enregistrer
        </Button>
      </div>

      {/* Master switches */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
        <MasterToggle
          label="Push (mobile)" icon={Smartphone}
          checked={prefs?.channels?.push}
          onChange={(v) => toggleMasterChannel("push", v)}
          testId="settings-notifications-master-push"
        />
        <MasterToggle
          label="E-mail" icon={Mail}
          checked={prefs?.channels?.email}
          onChange={(v) => toggleMasterChannel("email", v)}
          hint="Canal stubbé — actif à l'ajout de Resend"
          testId="settings-notifications-master-email"
        />
        <MasterToggle
          label="SMS" icon={MessageSquare}
          checked={prefs?.channels?.sms}
          onChange={(v) => toggleMasterChannel("sms", v)}
          hint="Canal stubbé — actif à l'ajout de Twilio"
          testId="settings-notifications-master-sms"
        />
      </div>

      {/* Admin: target user selector */}
      {isAdmin && users.length > 1 && (
        <div className="mb-5 flex items-center gap-3 flex-wrap">
          <span className="text-xs font-semibold text-slate-600">Utilisateur cible (test) :</span>
          <Select value={targetUserId} onValueChange={setTargetUserId}>
            <SelectTrigger className="h-8 w-72 text-xs" data-testid="settings-notifications-target-user">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {users.map((u) => (
                <SelectItem key={u.id} value={u.id}>{u.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-[10px] text-slate-400">
            Seuls les tests sont envoyés à l&apos;utilisateur sélectionné — les préférences modifiées
            ici concernent votre propre compte.
          </p>
        </div>
      )}

      {/* Core events */}
      <EventSection
        title="Événements LOGITRAK" subtitle="Identification chauffeur + sécurité"
        events={grouped.core} prefs={prefs}
        onToggle={togglePref}
        onTest={isAdmin ? testEvent : null}
        testingEvent={testing}
      />

      {/* Business events */}
      <EventSection
        title="Événements métier (à venir)"
        subtitle="Stubs — déclenchés automatiquement quand les jobs APScheduler seront ajoutés"
        events={grouped.business} prefs={prefs}
        onToggle={togglePref}
        onTest={isAdmin ? testEvent : null}
        testingEvent={testing}
        muted
      />
    </Card>
  );
}

function MasterToggle({ label, icon: Icon, checked, onChange, hint, testId }) {
  return (
    <div className="border border-slate-200 rounded-md p-3 bg-slate-50/30">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
          <Icon className="w-3.5 h-3.5 text-[#2196F3]" /> {label}
        </span>
        <Switch checked={!!checked} onCheckedChange={onChange} data-testid={testId} />
      </div>
      {hint && <p className="text-[10px] text-slate-400 mt-1">{hint}</p>}
    </div>
  );
}

function EventSection({ title, subtitle, events, prefs, onToggle, onTest, testingEvent, muted }) {
  if (!events.length) return null;
  return (
    <div className={`mt-2 ${muted ? "opacity-90" : ""}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</h3>
          {subtitle && <p className="text-[10px] text-slate-400 mt-0.5">{subtitle}</p>}
        </div>
      </div>

      <div className="border border-slate-200 rounded-md overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-50">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="text-left px-3 py-2 font-medium">Événement</th>
              <th className="text-center px-3 py-2 font-medium w-20">
                <span className="inline-flex items-center gap-1"><Smartphone className="w-3 h-3" /> Push</span>
              </th>
              <th className="text-center px-3 py-2 font-medium w-20">
                <span className="inline-flex items-center gap-1"><Mail className="w-3 h-3" /> Email</span>
              </th>
              <th className="text-center px-3 py-2 font-medium w-20">
                <span className="inline-flex items-center gap-1"><MessageSquare className="w-3 h-3" /> SMS</span>
              </th>
              {onTest && <th className="text-right px-3 py-2 font-medium w-28">Test</th>}
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => {
              const channels = prefs?.events?.[ev.event] || ev.default_channels;
              return (
                <tr key={ev.event}
                    data-testid={`settings-notifications-row-${ev.event}`}
                    className="border-t border-slate-100 hover:bg-slate-50/50">
                  <td className="px-3 py-2">
                    <p className="text-slate-800 font-medium">{ev.label}</p>
                    <p className="text-[10px] text-slate-400 font-mono">{ev.event} · audience {ev.audience}</p>
                  </td>
                  {["push", "email", "sms"].map((ch) => (
                    <td key={ch} className="px-3 py-2 text-center">
                      <Switch
                        checked={!!channels[ch]}
                        onCheckedChange={(v) => onToggle(ev.event, ch, v)}
                        data-testid={`settings-notifications-toggle-${ev.event}-${ch}`}
                      />
                    </td>
                  ))}
                  {onTest && (
                    <td className="px-3 py-2 text-right">
                      <Button
                        size="sm" variant="outline"
                        onClick={() => onTest(ev.event)}
                        disabled={testingEvent === ev.event}
                        className="h-7 px-2 text-[10px]"
                        data-testid={`settings-notifications-test-${ev.event}`}
                      >
                        {testingEvent === ev.event
                          ? <Loader2 className="w-3 h-3 animate-spin" />
                          : <Send className="w-3 h-3 mr-1" />}
                        Tester
                      </Button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
