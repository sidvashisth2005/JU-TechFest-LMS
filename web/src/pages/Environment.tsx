import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, errorText, type EnvPoint } from "../api";
import { useLive } from "../useLive";
import { Card, Empty, ErrorNote, LiveDot, Page, Stat } from "../components/ui";
import { dateTime, fmt, thiBand, timeOfDay } from "../format";

const RANGES = [
  { label: "24 h", hours: 24 },
  { label: "3 d", hours: 72 },
  { label: "7 d", hours: 168 },
];

export default function Environment() {
  const [points, setPoints] = useState<EnvPoint[]>([]);
  const [latest, setLatest] = useState<EnvPoint | null>(null);
  const [hours, setHours] = useState(24);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/api/env", { params: { hours } });
      setPoints(data.points);
      if (data.points.length) setLatest((l) => l ?? data.points[data.points.length - 1]);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [hours]);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 120_000);
    return () => window.clearInterval(t);
  }, [load]);

  const live = useLive((m) => {
    if (m.type === "env") setLatest(m as unknown as EnvPoint);
  });

  const band = thiBand(latest?.thi);
  const tick = hours > 48 ? dateTime : timeOfDay;
  const thiMax = Math.max(95, ...points.map((p) => p.thi ?? 0));

  return (
    <Page title="Barn environment" subtitle="Heat stress is the biggest everyday risk for dairy cattle" actions={<LiveDot state={live} />}>
      <ErrorNote text={error} />
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="THI" value={fmt(latest?.thi, 0)} hint={<span className={band.className}>{band.label}</span>} />
        <Stat label="Temperature" value={fmt(latest?.temp, 1, "°C")} />
        <Stat label="Humidity" value={fmt(latest?.humidity, 0, "%")} />
        <Stat label="Pressure" value={fmt(latest?.pressure, 0, " hPa")} />
      </div>

      <Card>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-forest-800">Trends</h2>
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
          <Empty>No barn readings yet.</Empty>
        ) : (
          <div className="space-y-6">
            <div>
              <h3 className="mb-1 font-medium text-forest-800">Temperature-humidity index</h3>
              <p className="mb-2 text-xs text-gray-500">
                Bands: under 72 comfortable · 72–79 mild · 79–89 moderate · 89+ severe heat stress
              </p>
              <div className="h-56">
                <ResponsiveContainer>
                  <LineChart data={points} syncId="env">
                    <ReferenceArea y1={72} y2={79} fill="#fde68a" fillOpacity={0.35} />
                    <ReferenceArea y1={79} y2={89} fill="#fdba74" fillOpacity={0.35} />
                    <ReferenceArea y1={89} y2={thiMax} fill="#fca5a5" fillOpacity={0.35} />
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="ts" tickFormatter={tick} minTickGap={40} fontSize={12} />
                    <YAxis domain={[60, thiMax]} fontSize={12} width={36} />
                    <Tooltip labelFormatter={(v) => dateTime(Number(v))} />
                    <Line type="monotone" dataKey="thi" name="THI" stroke="#9a3412" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div>
              <h3 className="mb-2 font-medium text-forest-800">Temperature (°C) and humidity (%)</h3>
              <div className="h-56">
                <ResponsiveContainer>
                  <LineChart data={points} syncId="env">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="ts" tickFormatter={tick} minTickGap={40} fontSize={12} />
                    <YAxis yAxisId="t" fontSize={12} width={36} />
                    <YAxis yAxisId="h" orientation="right" domain={[0, 100]} fontSize={12} width={36} />
                    <Tooltip labelFormatter={(v) => dateTime(Number(v))} />
                    <Line yAxisId="t" type="monotone" dataKey="temp" name="Temp °C" stroke="#ea580c" dot={false} strokeWidth={2} />
                    <Line yAxisId="h" type="monotone" dataKey="humidity" name="Humidity %" stroke="#0284c7" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </Card>
    </Page>
  );
}
