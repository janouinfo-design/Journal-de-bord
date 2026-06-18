import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Loader2, Mail, MessageSquare, Send, Smartphone } from "lucide-react";

/** Single notification event row. Pure presentational. */
function EventRow({ ev, channels, onToggle, onTest, testing }) {
  return (
    <tr
      data-testid={`settings-notifications-row-${ev.event}`}
      className="border-t border-slate-100 hover:bg-slate-50/50"
    >
      <td className="px-3 py-2">
        <p className="text-slate-800 font-medium">{ev.label}</p>
        <p className="text-[10px] text-slate-400 font-mono">
          {ev.event} · audience {ev.audience}
        </p>
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
            size="sm"
            variant="outline"
            onClick={() => onTest(ev.event)}
            disabled={testing}
            className="h-7 px-2 text-[10px]"
            data-testid={`settings-notifications-test-${ev.event}`}
          >
            {testing
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Send className="w-3 h-3 mr-1" />}
            Tester
          </Button>
        </td>
      )}
    </tr>
  );
}

/** Grouped table of notification events (e.g. "LOGITRAK" or "Métier futurs"). */
export default function NotificationEventSection({
  title, subtitle, events, prefs, onToggle, onTest, testingEvent, muted,
}) {
  if (!events?.length) return null;
  return (
    <div className={`mt-2 ${muted ? "opacity-90" : ""}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            {title}
          </h3>
          {subtitle && (
            <p className="text-[10px] text-slate-400 mt-0.5">{subtitle}</p>
          )}
        </div>
      </div>

      <div className="border border-slate-200 rounded-md overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-50">
            <tr className="text-[10px] uppercase tracking-wider text-slate-500">
              <th className="text-left px-3 py-2 font-medium">Événement</th>
              <th className="text-center px-3 py-2 font-medium w-20">
                <span className="inline-flex items-center gap-1">
                  <Smartphone className="w-3 h-3" /> Push
                </span>
              </th>
              <th className="text-center px-3 py-2 font-medium w-20">
                <span className="inline-flex items-center gap-1">
                  <Mail className="w-3 h-3" /> Email
                </span>
              </th>
              <th className="text-center px-3 py-2 font-medium w-20">
                <span className="inline-flex items-center gap-1">
                  <MessageSquare className="w-3 h-3" /> SMS
                </span>
              </th>
              {onTest && (
                <th className="text-right px-3 py-2 font-medium w-28">Test</th>
              )}
            </tr>
          </thead>
          <tbody>
            {events.map((ev) => (
              <EventRow
                key={ev.event}
                ev={ev}
                channels={prefs?.events?.[ev.event] || ev.default_channels}
                onToggle={onToggle}
                onTest={onTest}
                testing={testingEvent === ev.event}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
