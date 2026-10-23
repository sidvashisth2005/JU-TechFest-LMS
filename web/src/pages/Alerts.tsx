import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, errorText, type Alert, type Severity } from "../api";
import { useLive } from "../useLive";
import { Card, Empty, ErrorNote, LiveDot, Page, StatusChip } from "../components/ui";
import { dateTime, titleCase } from "../format";

export default function Alerts() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [severity, setSeverity] = useState<Severity | "">("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Alert[]>("/api/alerts", {
        params: { open: openOnly, severity: severity || undefined, limit: 500 },
      });
      setAlerts(data);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [openOnly, severity]);

  useEffect(() => {
    load();
  }, [load]);

  const live = useLive((m) => {
    if (m.type === "alert") load();
  });

  const ack = async (id: number) => {
    try {
      await api.post(`/api/alerts/${id}/ack`);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  };

  return (
    <Page title="Alerts" subtitle="Raised by the health rules and the anomaly detector" actions={<LiveDot state={live} />}>
      <ErrorNote text={error} />
      <Card>
        <div className="mb-4 flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
            Open only
          </label>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as Severity | "")}
            className="rounded-lg border bg-white px-2 py-1"
          >
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
          <span className="text-[hsl(var(--muted-foreground))]">{alerts.length} shown</span>
        </div>
        {alerts.length === 0 ? (
          <Empty>No alerts match.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-[hsl(var(--muted-foreground))]">
                <tr>
                  <th className="py-2 pr-3 font-medium">When</th>
                  <th className="py-2 pr-3 font-medium">Severity</th>
                  <th className="py-2 pr-3 font-medium">Animal</th>
                  <th className="py-2 pr-3 font-medium">Type</th>
                  <th className="py-2 pr-3 font-medium">Details</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {alerts.map((a) => (
                  <tr key={a.id} className="border-t align-top">
                    <td className="whitespace-nowrap py-2 pr-3 tabular-nums">{dateTime(a.ts)}</td>
                    <td className="py-2 pr-3"><StatusChip status={a.severity} /></td>
                    <td className="py-2 pr-3">
                      {a.animal_id ? (
                        <Link className="font-medium text-emerald-800 hover:underline" to={`/animals/${a.animal_id}`}>
                          {a.animal_id}
                        </Link>
                      ) : (
                        <span>Barn {a.station_id}</span>
                      )}
                    </td>
                    <td className="py-2 pr-3">{titleCase(a.kind)}</td>
                    <td className="py-2 pr-3 text-gray-700">{a.message}</td>
                    <td className="whitespace-nowrap py-2 text-right">
                      {a.acked_at ? (
                        <span className="text-xs text-gray-500">handled by {a.acked_by}</span>
                      ) : (
                        <button onClick={() => ack(a.id)} className="text-emerald-700 hover:underline">
                          Mark handled
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Page>
  );
}
