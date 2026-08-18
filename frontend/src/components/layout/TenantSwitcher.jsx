import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Building2 } from "lucide-react";

export const SA_TENANT_KEY = "sa_tenant_id";

export default function TenantSwitcher() {
  const [tenants, setTenants] = useState([]);
  const current = localStorage.getItem(SA_TENANT_KEY) || "none";

  useEffect(() => {
    api.get("/admin/tenants").then(({ data }) => setTenants(data)).catch(() => {});
  }, []);

  function onChange(value) {
    if (value === "none") localStorage.removeItem(SA_TENANT_KEY);
    else localStorage.setItem(SA_TENANT_KEY, value);
    window.location.assign(value === "none" ? "/admin/clients" : "/livre/dashboard");
  }

  return (
    <div className="flex items-center gap-2">
      <Building2 className="w-4 h-4 text-slate-400 shrink-0" />
      <Select value={current} onValueChange={onChange}>
        <SelectTrigger data-testid="tenant-switcher" className="h-9 w-[210px] text-sm">
          <SelectValue placeholder="Voir en tant que…" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none" data-testid="tenant-switcher-none">
            — Aucun client (admin) —
          </SelectItem>
          {tenants.map((t) => (
            <SelectItem key={t.id} value={t.id} data-testid={`tenant-switcher-${t.id}`}>
              {t.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
