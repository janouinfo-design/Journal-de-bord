/* Reusable horizontal sub-tabs component matching the top-nav style.
 *
 * Two flavours:
 *   1. Route-driven — passes `to` per item, uses NavLink for active state.
 *   2. State-driven — passes `value` + `onChange`, active tab is `currentValue`.
 *
 * Visual style intentionally lighter than the main top-nav (smaller text +
 * shorter underline) so the hierarchy is obvious.
 */
import { NavLink } from "react-router-dom";

/**
 * @param {Object[]} tabs — [{value|to, label, icon?, testId?}]
 * @param {string} [current] — currentValue for state-driven mode
 * @param {Function} [onChange] — value=>void for state-driven mode
 * @param {string} [className] — extra classes on wrapper
 */
export default function SubTabs({ tabs, current, onChange, className = "" }) {
  const isRouteMode = tabs.some((t) => t.to);
  return (
    <div
      className={`flex items-center gap-1 overflow-x-auto no-scrollbar border-b border-slate-200 -mb-px ${className}`}
      data-testid="sub-tabs"
    >
      {tabs.map((t) => {
        const Icon = t.icon;
        if (isRouteMode) {
          return (
            <NavLink
              key={t.to}
              to={t.to}
              end={!t.matchPrefix}
              data-testid={t.testId}
              className={({ isActive }) => activeCls(isActive)}
            >
              {Icon && <Icon className="w-3.5 h-3.5" />}
              <span>{t.label}</span>
            </NavLink>
          );
        }
        const active = current === t.value;
        return (
          <button
            key={t.value}
            type="button"
            data-testid={t.testId}
            onClick={() => onChange?.(t.value)}
            className={activeCls(active)}
          >
            {Icon && <Icon className="w-3.5 h-3.5" />}
            <span>{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function activeCls(active) {
  return [
    "flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors border-b-2 rounded-none",
    active
      ? "text-slate-900 border-slate-900"
      : "text-slate-500 border-transparent hover:text-slate-800",
  ].join(" ");
}
