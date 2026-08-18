import { Card } from "@/components/ui/card";

export function KpiCard({ label, value, sub, accent = "default", testId, icon: Icon }) {
  const accents = {
    default: "text-slate-900",
    pro: "text-[#2196F3]",
    perso: "text-slate-700",
    success: "text-emerald-600",
    warning: "text-amber-600",
  };
  return (
    <Card data-testid={testId} className="bg-white border-slate-200 shadow-sm hover:shadow-md transition-shadow rounded-md p-5">
      <div className="flex items-start justify-between">
        <p className="text-xs font-semibold tracking-[0.05em] uppercase text-slate-500">{label}</p>
        {Icon && (
          <div className="w-8 h-8 rounded-md bg-slate-50 flex items-center justify-center text-slate-500">
            <Icon className="w-4 h-4" />
          </div>
        )}
      </div>
      <p className={`mt-3 text-3xl font-semibold tracking-tight ${accents[accent]}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1.5">{sub}</p>}
    </Card>
  );
}
