export function ProBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 bg-blue-50 text-[#1976D2] border border-blue-200 px-2.5 py-0.5 rounded-full text-xs font-medium">
      <span className="w-1.5 h-1.5 rounded-full bg-[#2196F3]" /> Pro
    </span>
  );
}

export function PersoBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 bg-slate-100 text-slate-700 border border-slate-200 px-2.5 py-0.5 rounded-full text-xs font-medium">
      <span className="w-1.5 h-1.5 rounded-full bg-slate-400" /> Perso
    </span>
  );
}

export function ClassificationBadge({ value }) {
  return value === "professional" ? <ProBadge /> : <PersoBadge />;
}
