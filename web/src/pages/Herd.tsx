import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, Heart, Thermometer, WifiOff } from "lucide-react";
import { api, errorText, type Alert, type AnimalRow, type Summary } from "../api";
import { useLive, type LiveMessage } from "../useLive";
import { Card, Empty, ErrorNote, LiveDot, Page, Stat, StatusChip } from "../components/ui";
import { ago, fmt, STATUS_STYLE, thiBand, titleCase } from "../format";

type Filter = "all" | "attention" | "offline";

export default function Herd() {
  const [animals, setAnimals] = useState<AnimalRow[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [a, s, al] = await Promise.all([
        api.get<AnimalRow[]>("/api/animals"),
        api.get<Summary>("/api/summary"),
        api.get<Alert[]>("/api/alerts", { params: { limit: 8 } }),
      ]);
      setAnimals(a.data);
      setSummary(s.data);
      setAlerts(al.data);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 60_000); // statuses/online flags drift without new messages
    return () => window.clearInterval(t);
  }, [load]);

  const live = useLive((m: LiveMessage) => {
    if (m.type === "vitals") {
      const v = m as unknown as AnimalRow & { ts: number };
      setAnimals((prev) =>
        prev.map((a) =>
          a.animal_id === v.animal_id
            ? {
                ...a,
                hr: v.hr ?? a.hr,
                spo2: v.spo2 ?? a.spo2,
                body_temp: v.body_temp ?? a.body_temp,
                activity: v.activity ?? a.activity,
                battery: v.battery ?? a.battery,
                last_seen: v.ts,
                online: true,
              }
            : a,
        ),
      );
    } else if (m.type === "alert") {
      load(); // statuses and counts change; one refetch keeps it all consistent
    }
  });

  const shown = useMemo(() => {
    if (filter === "attention") return animals.filter((a) => a.status === "critical" || a.status === "warning");
    if (filter === "offline") return animals.filter((a) => !a.online);
    return animals;
  }, [animals, filter]);

  const env = summary?.environment?.[0];
  const band = thiBand(env?.thi);
  const critical = summary?.open_alerts.critical ?? 0;
  const warning = summary?.open_alerts.warning ?? 0;

  return (
    <Page title="Herd" subtitle="Every collar at a glance" actions={<LiveDot state={live} />}>
      <ErrorNote text={error} />
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Animals" value={summary?.animals ?? "—"} hint={`${summary?.online ?? 0} collars online`} />
        <Stat
          label="Need attention"
          value={critical + warning}
          hint={`${critical} critical · ${warning} watch`}
          tone={critical ? "!text-red-700" : ""}
        />
        <Stat label="Barn THI" value={fmt(env?.thi, 0)} hint={<span className={band.className}>{band.label}</span>} />
        <Stat
          label="Barn air"
          value={<span className="text-2xl">{fmt(env?.temp, 1, "°C")}</span>}
          hint={`${fmt(env?.humidity, 0, "%")} humidity`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xl font-semibold text-forest-800">Animals</h2>
            <div className="flex gap-1 rounded-xl bg-[hsl(var(--muted))] p-1 text-sm">
              {(["all", "attention", "offline"] as Filter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`rounded-lg px-3 py-1 ${filter === f ? "bg-white shadow-sm text-forest-800" : "text-[hsl(var(--muted-foreground))]"}`}
                >
                  {titleCase(f)}
                </button>
              ))}
            </div>
          </div>
          {loading ? (
            <Empty>Loading…</Empty>
          ) : shown.length === 0 ? (
            <Empty>{animals.length ? "Nothing here — all good." : "No collars have reported yet."}</Empty>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
              {shown.map((a) => (
                <Link
                  key={a.animal_id}
                  to={`/animals/${a.animal_id}`}
                  className={`rounded-xl border bg-white/90 p-3 transition hover:-translate-y-0.5 hover:shadow-md ${
                    a.status === "critical" ? "border-red-300" : a.status === "warning" ? "border-amber-300" : ""
                  }`}
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-semibold text-forest-800">{a.name || a.animal_id}</span>
                    {a.online ? (
                      <span className={`h-2.5 w-2.5 rounded-full ${STATUS_STYLE[a.status].dot}`} title={STATUS_STYLE[a.status].label} />
                    ) : (
                      <WifiOff className="h-4 w-4 text-gray-400" aria-label="offline" />
                    )}
                  </div>
                  <div className="space-y-0.5 text-sm tabular-nums text-gray-700">
                    <div className="flex items-center gap-1.5">
                      <Thermometer className="h-3.5 w-3.5 text-orange-500" /> {fmt(a.body_temp, 1, "°C")}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Heart className="h-3.5 w-3.5 text-rose-500" /> {fmt(a.hr, 0, " bpm")}
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Activity className="h-3.5 w-3.5 text-emerald-600" /> {fmt(a.activity, 3, " g")}
                    </div>
                  </div>
                  {!a.online && <div className="mt-1 text-xs text-gray-500">last seen {ago(a.last_seen)}</div>}
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-xl font-semibold text-forest-800">Open alerts</h2>
            <Link to="/alerts" className="text-sm text-emerald-700 hover:underline">All alerts →</Link>
          </div>
          {alerts.length === 0 ? (
            <Empty>No open alerts.</Empty>
          ) : (
            <ul className="space-y-3">
              {alerts.map((al) => (
                <li key={al.id} className="rounded-xl border bg-white/90 p-3">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <StatusChip status={al.severity} />
                    <span className="text-xs text-gray-500">{ago(al.ts)}</span>
                  </div>
                  <div className="text-sm text-gray-800">
                    {al.animal_id ? (
                      <Link to={`/animals/${al.animal_id}`} className="font-semibold text-forest-800 hover:underline">
                        {al.animal_id}
                      </Link>
                    ) : (
                      <span className="font-semibold text-forest-800">Barn</span>
                    )}{" "}
                    · {al.message}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </Page>
  );
}
