import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, Pencil } from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, errorText, type Alert, type HistoryPoint } from "../api";
import { useLive } from "../useLive";
import { Card, Empty, ErrorNote, Page, StatusChip } from "../components/ui";
import { ago, dateTime, fmt, timeOfDay, titleCase } from "../format";

interface AnimalInfo {
  animal_id: string;
  name: string | null;
  breed: string | null;
  sex: "F" | "M" | null;
  notes: string | null;
  first_seen: number;
  last_seen: number | null;
  online: boolean;
  latest: (HistoryPoint & { battery: number | null; rssi: number | null }) | null;
  open_alerts: Alert[];
}

const RANGES = [
  { label: "6 h", hours: 6 },
  { label: "24 h", hours: 24 },
  { label: "3 d", hours: 72 },
  { label: "7 d", hours: 168 },
];

export default function AnimalDetail() {
  const { id = "" } = useParams();
  const [info, setInfo] = useState<AnimalInfo | null>(null);
  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const [hours, setHours] = useState(24);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: "", breed: "", notes: "" });

  const loadInfo = useCallback(async () => {
    try {
      const { data } = await api.get<AnimalInfo>(`/api/animals/${id}`);
      setInfo(data);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [id]);

  const loadHistory = useCallback(async () => {
    try {
      const { data } = await api.get(`/api/animals/${id}/history`, { params: { hours } });
      setPoints(data.points);
    } catch (e) {
      setError(errorText(e));
    }
  }, [id, hours]);

  useEffect(() => {
    loadInfo();
  }, [loadInfo]);
  useEffect(() => {
    loadHistory();
    const t = window.setInterval(loadHistory, 60_000);
    return () => window.clearInterval(t);
  }, [loadHistory]);

  useLive((m) => {
    if (m.type === "vitals" && m.animal_id === id) {
      const reading = m as unknown as NonNullable<AnimalInfo["latest"]>;
      setInfo((prev) => (prev ? { ...prev, latest: { ...prev.latest, ...reading }, online: true } : prev));
    } else if (m.type === "alert" && m.animal_id === id) {
      loadInfo();
    }
  });

  const ack = async (alertId: number) => {
    try {
      await api.post(`/api/alerts/${alertId}/ack`);
      loadInfo();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const save = async () => {
    try {
      const { data } = await api.patch<AnimalInfo>(`/api/animals/${id}`, {
        name: form.name || null,
        breed: form.breed || null,
        notes: form.notes || null,
      });
      setInfo(data);
      setEditing(false);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const startEdit = () => {
    setForm({ name: info?.name ?? "", breed: info?.breed ?? "", notes: info?.notes ?? "" });
    setEditing(true);
  };

  const l = info?.latest;
  const tick = hours > 48 ? dateTime : timeOfDay;

  return (
    <Page
      title={info?.name ? `${info.name} (${id})` : `Cow ${id}`}
      subtitle={
        info ? (
          <>
            {info.breed ?? "Breed not set"} · {info.online ? "collar online" : `offline, last seen ${ago(info.last_seen)}`}
          </>
        ) : undefined
      }
      actions={
        <Link to="/herd" className="btn-secondary !px-4 !py-2 text-sm">
          <ArrowLeft className="h-4 w-4" /> Herd
        </Link>
      }
    >
      <ErrorNote text={error} />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5">
        {[
          ["Temperature", fmt(l?.body_temp, 1, " °C")],
          ["Heart rate", fmt(l?.hr, 0, " bpm")],
          ["SpO₂", fmt(l?.spo2, 0, " %")],
          ["Activity", fmt(l?.activity, 3, " g")],
          ["Collar battery", fmt(l?.battery, 2, " V")],
        ].map(([label, value]) => (
          <Card key={label}>
            <div className="text-sm text-[hsl(var(--muted-foreground))]">{label}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-forest-800">{value}</div>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-xl font-semibold text-forest-800">History</h2>
            <div className="flex gap-1 rounded-xl bg-[hsl(var(--muted))] p-1 text-sm">
              {RANGES.map((r) => (
                <button
                  key={r.hours}
                  onClick={() => setHours(r.hours)}
                  className={`rounded-lg px-3 py-1 ${hours === r.hours ? "bg-white text-forest-800 shadow-sm" : "text-[hsl(var(--muted-foreground))]"}`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          {points.length === 0 ? (
            <Empty>No readings in this period.</Empty>
          ) : (
            <div className="space-y-6">
              <Chart title="Body temperature (°C)" note="dashed line: fever threshold 39.5 °C">
                <LineChart data={points} syncId="animal">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="ts" tickFormatter={tick} minTickGap={40} fontSize={12} />
                  <YAxis domain={["dataMin - 0.3", "dataMax + 0.3"]} tickFormatter={(v) => v.toFixed(1)} fontSize={12} width={40} />
                  <Tooltip labelFormatter={(v) => dateTime(Number(v))} formatter={(v: number) => v?.toFixed(2)} />
                  <ReferenceLine y={39.5} stroke="#dc2626" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="body_temp" name="Temp" stroke="#ea580c" dot={false} strokeWidth={2} />
                </LineChart>
              </Chart>
              <Chart title="Heart rate (bpm)">
                <LineChart data={points} syncId="animal">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="ts" tickFormatter={tick} minTickGap={40} fontSize={12} />
                  <YAxis domain={["dataMin - 5", "dataMax + 5"]} tickFormatter={(v) => v.toFixed(0)} fontSize={12} width={40} />
                  <Tooltip labelFormatter={(v) => dateTime(Number(v))} formatter={(v: number) => v?.toFixed(0)} />
                  <Line type="monotone" dataKey="hr" name="HR" stroke="#e11d48" dot={false} strokeWidth={2} connectNulls />
                </LineChart>
              </Chart>
              <Chart title="Activity (g)">
                <AreaChart data={points} syncId="animal">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="ts" tickFormatter={tick} minTickGap={40} fontSize={12} />
                  <YAxis tickFormatter={(v) => v.toFixed(2)} fontSize={12} width={40} />
                  <Tooltip labelFormatter={(v) => dateTime(Number(v))} formatter={(v: number) => v?.toFixed(3)} />
                  <Area type="monotone" dataKey="activity" name="Activity" stroke="#059669" fill="#a7f3d0" />
                </AreaChart>
              </Chart>
            </div>
          )}
        </Card>

        <div className="space-y-6">
          <Card>
            <h2 className="mb-3 text-xl font-semibold text-forest-800">Open alerts</h2>
            {info && info.open_alerts.length === 0 ? (
              <Empty>Nothing open.</Empty>
            ) : (
              <ul className="space-y-3">
                {info?.open_alerts.map((a) => (
                  <li key={a.id} className="rounded-xl border bg-white/90 p-3">
                    <div className="mb-1 flex items-center justify-between">
                      <StatusChip status={a.severity} />
                      <span className="text-xs text-gray-500">{ago(a.ts)}</span>
                    </div>
                    <div className="text-sm font-medium text-gray-800">{titleCase(a.kind)}</div>
                    <div className="text-sm text-gray-700">{a.message}</div>
                    <button onClick={() => ack(a.id)} className="mt-2 text-sm text-emerald-700 hover:underline">
                      Mark as handled
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xl font-semibold text-forest-800">Details</h2>
              {!editing ? (
                <button onClick={startEdit} className="text-emerald-700" aria-label="Edit details">
                  <Pencil className="h-4 w-4" />
                </button>
              ) : (
                <button onClick={save} className="text-emerald-700" aria-label="Save details">
                  <Check className="h-5 w-5" />
                </button>
              )}
            </div>
            {editing ? (
              <div className="space-y-2 text-sm">
                {(["name", "breed"] as const).map((k) => (
                  <input
                    key={k}
                    placeholder={titleCase(k)}
                    value={form[k]}
                    onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                    className="w-full rounded-lg border bg-white px-3 py-1.5"
                  />
                ))}
                <textarea
                  placeholder="Notes"
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  className="h-20 w-full rounded-lg border bg-white px-3 py-1.5"
                />
              </div>
            ) : (
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                <dt className="text-gray-500">Name</dt>
                <dd>{info?.name ?? "—"}</dd>
                <dt className="text-gray-500">Breed</dt>
                <dd>{info?.breed ?? "—"}</dd>
                <dt className="text-gray-500">First seen</dt>
                <dd>{info ? dateTime(info.first_seen) : "—"}</dd>
                <dt className="text-gray-500">Notes</dt>
                <dd className="whitespace-pre-wrap">{info?.notes ?? "—"}</dd>
              </dl>
            )}
          </Card>
        </div>
      </div>
    </Page>
  );
}

function Chart({ title, note, children }: { title: string; note?: string; children: React.ReactElement }) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="font-medium text-forest-800">{title}</h3>
        {note && <span className="text-xs text-gray-500">{note}</span>}
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          {children}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
