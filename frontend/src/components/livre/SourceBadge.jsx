import { Badge } from "@/components/ui/badge";

const STYLES = {
  "APP":         "bg-blue-50 text-blue-700 border-blue-200",
  "BLE":         "bg-cyan-50 text-cyan-700 border-cyan-200",
  "APP+BLE":     "bg-emerald-50 text-emerald-700 border-emerald-200",
  "MANUEL":      "bg-violet-50 text-violet-700 border-violet-200",
  "AFFECTATION": "bg-slate-100 text-slate-600 border-slate-200",
};

export const SourceBadge = ({ source, className = "" }) => {
  if (!source) return <span className="text-xs text-slate-400">—</span>;
  const style = STYLES[source] || STYLES.AFFECTATION;
  return (
    <Badge variant="outline" className={`${style} font-mono text-[10px] tracking-wider ${className}`}
           data-testid={`source-badge-${source}`}>
      {source}
    </Badge>
  );
};
