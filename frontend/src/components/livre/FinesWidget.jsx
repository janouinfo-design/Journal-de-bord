/* Compact KPI widget that surfaces fine-management info on the main fleet
 * dashboard. Calls /livre/fines/stats/summary and clicks through to the
 * dedicated Fines management section.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtAmount } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Receipt, AlertTriangle, ChevronRight } from "lucide-react";

export default function FinesWidget() {
  const [data, setData] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.get("/livre/fines/stats/summary")
      .then(r => { if (!cancelled) setData(r.data); })
      .catch(() => { /* not allowed for drivers — silently skip */ });
    return () => { cancelled = true; };
  }, []);

  if (!data) return null;
  const open = (data.by_status?.to_pay || 0)
    + (data.by_status?.to_analyze || 0)
    + (data.by_status?.received || 0)
    + (data.by_status?.disputed || 0)
    + (data.by_status?.driver_to_identify || 0)
    + (data.by_status?.awaiting_driver || 0);
  const pendingAmount = (data.total_amount || 0) - (data.paid_amount || 0);

  return (
    <Link to="/livre/amendes" className="block group" data-testid="dashboard-fines-widget">
      <Card className="p-4 bg-gradient-to-br from-rose-50 to-amber-50 border-rose-100
                       hover:shadow-md transition-shadow">
        <div className="flex items-start justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-white border border-rose-200">
              <Receipt className="w-4 h-4 text-rose-600" />
            </div>
            <span className="text-[10px] uppercase tracking-[0.14em] text-rose-700 font-semibold">
              Amendes
            </span>
          </div>
          <ChevronRight className="w-4 h-4 text-rose-400 group-hover:translate-x-1 transition-transform" />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <p className="text-[10px] text-slate-500">Total</p>
            <p className="text-xl font-semibold text-slate-900" data-testid="dashboard-fines-total">{data.total}</p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500 flex items-center gap-1">
              <AlertTriangle className="w-2.5 h-2.5" /> Ouvert
            </p>
            <p className="text-xl font-semibold text-amber-700" data-testid="dashboard-fines-open">{open}</p>
          </div>
          <div>
            <p className="text-[10px] text-slate-500">À payer</p>
            <p className="text-sm font-semibold text-rose-700 mt-1.5" data-testid="dashboard-fines-amount">
              {fmtAmount(pendingAmount)}
            </p>
          </div>
        </div>
      </Card>
    </Link>
  );
}
