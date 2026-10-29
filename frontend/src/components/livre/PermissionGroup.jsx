import { Checkbox } from "@/components/ui/checkbox";
import { ShieldAlert } from "lucide-react";

// Une ligne par permission : état effectif + origine (rôle / accordée / retirée / implicite).
export default function PermissionGroup({ title, hint, perms, state, onToggle }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-semibold">{title}</p>
        {hint && <p className="text-[11px] text-slate-400">{hint}</p>}
      </div>
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
        {perms.map((p) => {
          const s = state(p);
          return (
            <label key={p.code} className={`flex items-center justify-between gap-3 px-3 py-2 ${s.disabled ? "opacity-60" : "cursor-pointer hover:bg-slate-50/70"}`}>
              <div className="flex items-center gap-3 min-w-0">
                <Checkbox data-testid={`perm-${p.code}`} checked={s.effective} disabled={s.disabled}
                          onCheckedChange={(v) => onToggle(p, !!v)} />
                <div className="min-w-0">
                  <p className="text-sm text-slate-800 flex items-center gap-1.5">
                    {p.label}
                    {p.sensitive && <ShieldAlert className="w-3.5 h-3.5 text-amber-600" title="Permission sensible" />}
                  </p>
                  <p className="text-[11px] text-slate-400 font-mono">{p.code}{s.disabledReason ? ` · ${s.disabledReason}` : ""}</p>
                </div>
              </div>
              <span data-testid={`perm-origin-${p.code}`}
                    className={`shrink-0 text-[10px] uppercase tracking-wider font-semibold rounded-full px-2 py-0.5 ${s.badgeCls}`}>
                {s.badge}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
