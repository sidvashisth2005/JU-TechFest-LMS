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
import {
  BellOff,
  Compass,
  DoorClosed,
  DoorOpen,
  Hand,
  Magnet,
  Power,
  RotateCcw,
  TriangleAlert,
  Vibrate,
  type LucideIcon,
} from "lucide-react";
import { api, errorText, type EnvPoint, type StationEvent, type StationInfo } from "../api";
import { useLive } from "../useLive";
import { Card, Empty, ErrorNote, LiveDot, Page, Stat } from "../components/ui";
import { ago, compassLabel, dateTime, dewPoint, fmt, thiBand, timeOfDay } from "../format";

const RANGES = [
  { label: "24 h", hours: 24 },
  { label: "3 d", hours: 72 },
  { label: "7 d", hours: 168 },
];

const EVENT_INFO: Record<StationEvent["kind"], { icon: LucideIcon; label: string; tone: string }> = {
  knock: { icon: Hand, label: "Station bumped", tone: "text-sky-700" },
  tilted: { icon: TriangleAlert, label: "Station tilted", tone: "text-orange-600" },
  level: { icon: RotateCcw, label: "Station upright again", tone: "text-emerald-700" },
  gate_open: { icon: DoorOpen, label: "Gate open", tone: "text-orange-600" },
  gate_closed: { icon: DoorClosed, label: "Gate closed", tone: "text-emerald-700" },
  ack: { icon: BellOff, label: "Alerts acknowledged on the station joystick", tone: "text-forest-800" },
  hello: { icon: Power, label: "Station started", tone: "text-gray-600" },
};

function eventText(e: StationEvent): string {
  const v = e.value;
  if (e.kind === "knock" && v !== null) return `${v.toFixed(1)} g`;
  if (e.kind === "tilted" && v !== null) return `${v.toFixed(0)}°`;
  if ((e.kind === "gate_open" || e.kind === "gate_closed") && v !== null) return `${Math.round(v / 60)} min`;
  if (e.kind === "hello" && e.detail) return e.detail.replace(/^ip /, "IP ");
  return "";
}

function pressureHint(trend: number | null | undefined) {
  if (trend === null || trend === undefined) return "3 h trend: collecting…";
  const arrow = trend <= -0.5 ? "▼" : trend >= 0.5 ? "▲" : "▶";
  const text = `${arrow} ${trend > 0 ? "+" : ""}${trend.toFixed(1)} hPa in 3 h`;
  if (trend <= -3) return <span className="text-orange-600">{text} · storm likely</span>;
  return text;
}

function StationCard({ s }: { s: StationInfo }) {
  const ip = s.hello?.replace(/^ip /, "");
  const tilted = (s.tilt ?? 0) >= 30;
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${s.online ? "bg-emerald-500" : "bg-gray-400"}`} />
          <h3 className="font-semibold text-forest-800">{s.name || s.station_id}</h3>
          <span className="text-xs text-gray-500">{s.online ? "online" : `offline · ${ago(s.last_seen)}`}</span>
        </div>
        <div className="text-xs text-gray-500">
          {ip && <span className="mr-3">IP {ip}</span>}
          {s.open_alerts > 0 ? (
            <span className="font-medium text-orange-600">{s.open_alerts} open alert{s.open_alerts === 1 ? "" : "s"}</span>
          ) : (
            <span>no open alerts</span>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
        <Mini icon={TriangleAlert} label="Tilt" value={fmt(s.tilt, 0, "°")} hint={tilted ? "Tilted" : "Level"} warn={tilted} />
        <Mini icon={Vibrate} label="Vibration" value={fmt(s.vibration, 3, " g")} hint="RMS since last reading" />
        <Mini icon={Compass} label="Facing" value={`${compassLabel(s.heading)} ${fmt(s.heading, 0, "°")}`} hint="uncalibrated compass" />
        <Mini
          icon={s.gate === "gate_open" ? DoorOpen : Magnet}
          label={s.gate ? "Gate" : "Magnetic field"}
          value={s.gate ? (s.gate === "gate_open" ? "Open" : "Closed") : fmt(s.magnetic, 0, " µT")}
          hint={s.gate ? `field ${fmt(s.magnetic, 0, " µT")}` : "gate sensor off"}
          warn={s.gate === "gate_open"}
        />
      </div>
    </Card>
  );
}

function Mini({ icon: Icon, label, value, hint, warn }: {
  icon: LucideIcon;
  label: string;
  value: string;
  hint?: string;
  warn?: boolean;
}) {
  return (
    <div className="rounded-xl bg-white/60 p-3">
      <div className="flex items-center gap-1.5 text-xs text-gray-500">
        <Icon className="h-3.5 w-3.5" /> {label}
      </div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${warn ? "text-orange-600" : "text-forest-800"}`}>{value}</div>
      {hint && <div className="text-xs text-gray-500">{hint}</div>}
    </div>
  );
}

export default function Environment() {
  const [points, setPoints] = useState<EnvPoint[]>([]);
  const [latest, setLatest] = useState<EnvPoint | null>(null);
  const [stations, setStations] = useState<StationInfo[]>([]);
  const [events, setEvents] = useState<StationEvent[]>([]);
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

  const loadStations = useCallback(async () => {
    try {
      const [st, ev] = await Promise.all([
        api.get<StationInfo[]>("/api/stations"),
        api.get<StationEvent[]>("/api/stations/events", { params: { hours: 72, limit: 30 } }),
      ]);
      setStations(st.data);
      setEvents(ev.data);
    } catch (e) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 120_000);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => {
    loadStations();
    const t = window.setInterval(loadStations, 30_000);
    return () => window.clearInterval(t);
  }, [loadStations]);

  const live = useLive((m) => {
    if (m.type === "env") {
      const e = m as unknown as EnvPoint;
      setLatest({ ...e, dew_point: dewPoint(e.temp, e.humidity) });
    } else if (m.type === "station_event") {
      setEvents((list) => [m as unknown as StationEvent, ...list].slice(0, 30));
      loadStations();
    }
  });

  const band = thiBand(latest?.thi);
  const tick = hours > 48 ? dateTime : timeOfDay;
  const thiMax = Math.max(95, ...points.map((p) => p.thi ?? 0));
  const trend = stations.find((s) => s.station_id === latest?.station_id)?.pressure_trend_3h;
  const hasPressure = points.some((p) => p.pressure !== null);

  return (
    <Page title="Barn environment" subtitle="Heat stress is the biggest everyday risk for dairy cattle" actions={<LiveDot state={live} />}>
      <ErrorNote text={error} />
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="THI" value={fmt(latest?.thi, 0)} hint={<span className={band.className}>{band.label}</span>} />
        <Stat label="Temperature" value={fmt(latest?.temp, 1, "°C")} />
        <Stat label="Humidity" value={fmt(latest?.humidity, 0, "%")} />
        <Stat
          label="Dew point"
          value={fmt(latest?.dew_point ?? dewPoint(latest?.temp, latest?.humidity), 1, "°C")}
          hint="surfaces colder than this get wet"
        />
        <Stat label="Pressure" value={fmt(latest?.pressure, 0, " hPa")} hint={pressureHint(trend)} />
      </div>

      {stations.length > 0 && (
        <div className="mb-6 space-y-4">
          {stations.map((s) => (
            <StationCard key={s.station_id} s={s} />
          ))}
        </div>
      )}

      <Card className="mb-6">
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
              <h3 className="mb-2 font-medium text-forest-800">Temperature and dew point (°C), humidity (%)</h3>
              <div className="h-56">
                <ResponsiveContainer>
                  <LineChart data={points} syncId="env">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="ts" tickFormatter={tick} minTickGap={40} fontSize={12} />
                    <YAxis yAxisId="t" fontSize={12} width={36} />
                    <YAxis yAxisId="h" orientation="right" domain={[0, 100]} fontSize={12} width={36} />
                    <Tooltip labelFormatter={(v) => dateTime(Number(v))} />
                    <Line yAxisId="t" type="monotone" dataKey="temp" name="Temp °C" stroke="#ea580c" dot={false} strokeWidth={2} />
                    <Line yAxisId="t" type="monotone" dataKey="dew_point" name="Dew point °C" stroke="#0d9488" dot={false} strokeWidth={1.5} strokeDasharray="4 3" />
                    <Line yAxisId="h" type="monotone" dataKey="humidity" name="Humidity %" stroke="#0284c7" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
            {hasPressure && (
              <div>
                <h3 className="mb-1 font-medium text-forest-800">Air pressure (hPa)</h3>
                <p className="mb-2 text-xs text-gray-500">A fall of 3 hPa or more in 3 hours usually means a storm or heavy rain is coming</p>
                <div className="h-44">
                  <ResponsiveContainer>
                    <LineChart data={points} syncId="env">
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis dataKey="ts" tickFormatter={tick} minTickGap={40} fontSize={12} />
                      <YAxis domain={["dataMin - 2", "dataMax + 2"]} fontSize={12} width={44} tickFormatter={(v) => Number(v).toFixed(0)} />
                      <Tooltip labelFormatter={(v) => dateTime(Number(v))} />
                      <Line type="monotone" dataKey="pressure" name="Pressure hPa" stroke="#7c3aed" dot={false} strokeWidth={2} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="mb-3 text-xl font-semibold text-forest-800">Station events</h2>
        {events.length === 0 ? (
          <Empty>No events in the last 3 days. Bumps, tilts, gate and joystick actions show up here.</Empty>
        ) : (
          <ul className="divide-y divide-gray-100">
            {events.map((e, i) => {
              const info = EVENT_INFO[e.kind] ?? EVENT_INFO.hello;
              const Icon = info.icon;
              return (
                <li key={`${e.ts}-${e.kind}-${i}`} className="flex items-center gap-3 py-2 text-sm">
                  <Icon className={`h-4 w-4 shrink-0 ${info.tone}`} />
                  <span className="text-forest-800">{info.label}</span>
                  <span className="text-gray-500">{eventText(e)}</span>
                  <span className="ml-auto whitespace-nowrap text-xs text-gray-500">
                    {e.station_id} · {dateTime(e.ts)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </Page>
  );
}
