import { Badge } from "@/components/ui/badge";

const STYLES = {
  measured:    { label: "Mesuré",       cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  estimated:   { label: "Estimé",       cls: "bg-amber-50 text-amber-700 border-amber-200" },
  reference:   { label: "Référence",    cls: "bg-blue-50 text-blue-700 border-blue-200" },
  stale:       { label: "Périmé",       cls: "bg-orange-50 text-orange-700 border-orange-200" },
  unavailable: { label: "Indisponible", cls: "bg-slate-100 text-slate-500 border-slate-200" },
};

export function badgeKindForMetric(metric) {
  if (!metric || metric.availability === "UNAVAILABLE" || metric.value == null) return "unavailable";
  if (metric.availability === "STALE") return "stale";
  if (metric.measurement_type === "MEASURED") return "measured";
  if (metric.measurement_type === "ESTIMATED") return "estimated";
  if (metric.measurement_type === "REFERENCE") return "reference";
  return "unavailable";
}

export function EnergyBadge({ kind, metric, testId }) {
  const k = kind || badgeKindForMetric(metric);
  const s = STYLES[k] || STYLES.unavailable;
  return (
    <Badge variant="outline" data-testid={testId} className={`${s.cls} font-medium text-[10px] px-1.5 py-0`}>
      {s.label}
    </Badge>
  );
}
