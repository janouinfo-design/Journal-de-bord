/** Visual 24h timeline showing enabled work periods.
 * Highlights blue bands for professional time, grey for personal.
 * Each band is positioned with % of 24h.
 */
export default function DayTimeline({ periods, dayType }) {
  if (dayType === "personal") {
    return (
      <div className="relative h-6 w-full rounded-md bg-slate-200/70 overflow-hidden border border-slate-200" data-testid="timeline-personal">
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wider">Personnel toute la journée</span>
        </div>
        <Ticks />
      </div>
    );
  }

  const bands = (periods || []).filter(p =>
    p.enabled && _toMin(p.from) < _toMin(p.to)
  );

  return (
    <div className="relative h-6 w-full rounded-md bg-slate-100 overflow-hidden border border-slate-200" data-testid="timeline-work">
      {bands.map((p, i) => {
        const from = (_toMin(p.from) / 1440) * 100;
        const to = (_toMin(p.to) / 1440) * 100;
        return (
          <div
            key={`band-${p.from}-${p.to}-${i}`}
            className="absolute top-0 bottom-0 bg-[#2196F3]"
            style={{ left: `${from}%`, width: `${Math.max(to - from, 0.5)}%` }}
            title={`${p.from} → ${p.to}`}
          />
        );
      })}
      <Ticks />
    </div>
  );
}

function Ticks() {
  // Hour ticks every 3h
  return (
    <div className="absolute inset-0 flex pointer-events-none">
      {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
        <div
          key={h}
          className="absolute top-0 bottom-0 border-l border-white/50 flex items-end pb-0.5"
          style={{ left: `${(h / 24) * 100}%` }}
        >
          <span className="text-[9px] text-slate-100 font-mono pl-0.5 mix-blend-difference">{h}</span>
        </div>
      ))}
    </div>
  );
}

function _toMin(s) {
  if (!s) return 0;
  const [h, m] = s.split(":");
  return parseInt(h, 10) * 60 + parseInt(m, 10);
}
