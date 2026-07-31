import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmtDateTime } from "@/lib/api";
import { Bell, CheckCheck } from "lucide-react";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";

export default function NotificationsBell() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState({ items: [], unread: 0 });

  const load = useCallback(() => {
    api.get("/livre/notifications/inbox", { params: { limit: 20 } })
      .then(({ data }) => setData(data))
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  async function openItem(n) {
    if (!n.read) {
      try { await api.post(`/livre/notifications/inbox/${n.id}/read`); } catch { /* noop */ }
    }
    setOpen(false);
    load();
    if (n.link) navigate(n.link);
  }

  async function markAll() {
    try { await api.post("/livre/notifications/inbox/read-all"); load(); } catch { /* noop */ }
  }

  return (
    <Popover open={open} onOpenChange={(o) => { setOpen(o); if (o) load(); }}>
      <PopoverTrigger asChild>
        <button data-testid="notifications-bell"
                className="relative p-2 rounded-md hover:bg-slate-50 transition-colors"
                aria-label="Notifications">
          <Bell className="w-5 h-5 text-slate-600" />
          {data.unread > 0 && (
            <span data-testid="notifications-badge"
                  className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-600 text-white text-[10px] font-bold flex items-center justify-center">
              {data.unread > 99 ? "99+" : data.unread}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0" data-testid="notifications-panel">
        <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-slate-100">
          <p className="text-sm font-semibold text-slate-800">Notifications</p>
          {data.unread > 0 && (
            <Button data-testid="notifications-mark-all-read" variant="ghost" size="sm"
                    className="h-7 text-xs text-slate-500" onClick={markAll}>
              <CheckCheck className="w-3.5 h-3.5 mr-1" /> Tout marquer lu
            </Button>
          )}
        </div>
        <div className="max-h-96 overflow-y-auto">
          {data.items.length === 0 ? (
            <p data-testid="notifications-empty" className="p-6 text-center text-sm text-slate-400">
              Aucune notification
            </p>
          ) : data.items.map((n) => (
            <button key={n.id} type="button" data-testid={`notification-item-${n.id}`}
                    onClick={() => openItem(n)}
                    className={`w-full text-left px-3.5 py-2.5 border-b border-slate-50 hover:bg-slate-50 transition-colors ${n.read ? "opacity-60" : ""}`}>
              <div className="flex items-start gap-2">
                {!n.read && <span className="w-2 h-2 rounded-full bg-[#2196F3] mt-1.5 shrink-0" />}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-800 truncate">{n.title}</p>
                  <p className="text-xs text-slate-500 line-clamp-2">{n.body}</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">{fmtDateTime(n.created_at)}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
