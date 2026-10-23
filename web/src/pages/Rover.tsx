import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bot, Hand, OctagonX, Pause, Power } from "lucide-react";
import { api, authedUrl, errorText } from "../api";
import { Card, ErrorNote, Page } from "../components/ui";
import { fmt } from "../format";

type Mode = "idle" | "manual" | "follow";
type Direction = "forward" | "backward" | "left" | "right" | "stop";

interface RoverStatus {
  rover_id: string;
  mode: Mode;
  battery: number | null;
  distance_cm: number | null;
  blocked: boolean;
  left_dps: number;
  right_dps: number;
  camera: string;
  detector: string;
  targets: number;
  seen?: Record<string, number>;
  fps: number | null;
  mock: boolean;
  stop_cm?: number;
  person_close?: boolean;
  safety?: string | null;
}

/** Why forward motion is blocked, in words: the rover's own reason, else person, else obstacle. */
function blockedText(s: RoverStatus): string {
  if (s.safety) return `${s.safety[0].toUpperCase()}${s.safety.slice(1)} — stopped`;
  if (s.person_close) return "Person close — forward blocked";
  if (s.distance_cm != null) return `Obstacle ${s.distance_cm.toFixed(0)} cm — forward blocked`;
  return "Obstacle very close — forward blocked";
}

const KEYS: Record<string, Direction> = {
  w: "forward", arrowup: "forward",
  s: "backward", arrowdown: "backward",
  a: "left", arrowleft: "left",
  d: "right", arrowright: "right",
  " ": "stop", x: "stop",
};
const REPEAT_MS = 200; // the rover stops by itself if commands stop arriving (watchdog)

export default function Rover() {
  const [status, setStatus] = useState<RoverStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [speed, setSpeed] = useState(40);
  const [held, setHeld] = useState<Direction | null>(null);
  const [streamKey, setStreamKey] = useState(0);
  const repeat = useRef<number | undefined>(undefined);

  const poll = useCallback(async () => {
    try {
      const { data } = await api.get<RoverStatus>("/api/rover/status");
      setStatus(data);
      setError(null);
    } catch (e) {
      setStatus(null);
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    poll();
    const t = window.setInterval(poll, 1000);
    return () => window.clearInterval(t);
  }, [poll]);

  const send = useCallback(
    async (direction: Direction) => {
      try {
        await api.post("/api/rover/control", { direction, speed });
      } catch (e) {
        setError(errorText(e));
      }
    },
    [speed],
  );

  const start = useCallback(
    (d: Direction) => {
      window.clearInterval(repeat.current);
      setHeld(d);
      send(d);
      if (d !== "stop") repeat.current = window.setInterval(() => send(d), REPEAT_MS);
    },
    [send],
  );

  const release = useCallback(() => {
    window.clearInterval(repeat.current);
    repeat.current = undefined;
    setHeld(null);
    send("stop");
  }, [send]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const d = KEYS[e.key.toLowerCase()];
      if (!d || e.repeat || (e.target as HTMLElement)?.tagName === "INPUT") return;
      e.preventDefault();
      start(d);
    };
    const up = (e: KeyboardEvent) => {
      if (KEYS[e.key.toLowerCase()]) release();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", release);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", release);
      window.clearInterval(repeat.current);
    };
  }, [start, release]);

  const setMode = async (mode: Mode) => {
    try {
      await api.post("/api/rover/mode", { mode });
      poll();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const [stopped, setStopped] = useState<string | null>(null);

  const shutdown = async () => {
    const sure = window.confirm(
      "Stop the rover and the dashboard?\n\nThe rover's Pi shuts down cleanly and this dashboard goes offline. " +
        "Switch the rover on again to bring both back (the link comes on Telegram).",
    );
    if (!sure) return;
    try {
      const { data } = await api.post("/api/rover/shutdown");
      setStopped(`Rover: ${data.rover}. Dashboard: ${data.dashboard}.`);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const online = status !== null;
  const dist = status?.distance_cm;

  if (stopped) {
    return (
      <Page title="Rover and dashboard stopped" subtitle={stopped}>
        <Card>
          <div className="flex items-start gap-3">
            <Power className="mt-1 h-6 w-6 shrink-0 text-red-600" />
            <div className="space-y-2 text-forest-800">
              <p>The rover's Pi is shutting down. Wait until its green light stops blinking before switching the power off.</p>
              <p>This dashboard goes offline in a few seconds.</p>
              <p className="font-semibold">To start again: switch the rover on. About a minute later the dashboard is back and its link arrives on Telegram.</p>
            </div>
          </div>
        </Card>
      </Page>
    );
  }

  return (
    <Page
      title="Rover"
      subtitle={online ? `${status.rover_id} · camera ${status.camera} · detector ${status.detector}${status.mock ? " · simulated hardware" : ""}` : "Not connected"}
      actions={
        <button
          onClick={shutdown}
          className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-700"
        >
          <Power className="h-4 w-4" /> Stop rover &amp; dashboard
        </button>
      }
    >
      <ErrorNote text={error} />
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <Card className="!p-3">
          <div className="relative aspect-[4/3] overflow-hidden rounded-xl bg-black">
            {online ? (
              <img
                key={streamKey}
                src={authedUrl("/api/rover/stream.mjpg")}
                onError={() => window.setTimeout(() => setStreamKey((k) => k + 1), 2000)}
                alt="Rover camera"
                className="h-full w-full object-contain"
              />
            ) : (
              <div className="flex h-full items-center justify-center text-gray-400">Rover offline</div>
            )}
            {status?.blocked && (
              <div className="absolute bottom-3 left-3 rounded-lg bg-red-600 px-3 py-1 text-sm font-semibold text-white">
                {blockedText(status)}
              </div>
            )}
            {status?.fps != null && (
              <div className="absolute bottom-3 right-3 rounded bg-black/60 px-2 py-0.5 text-xs text-white">
                {status.fps.toFixed(0)} fps
              </div>
            )}
          </div>
        </Card>

        <div className="space-y-6">
          <Card>
            <h2 className="mb-3 text-xl font-semibold text-forest-800">Mode</h2>
            <div className="grid grid-cols-3 gap-2">
              {([
                ["idle", Pause, "Idle"],
                ["manual", Hand, "Manual"],
                ["follow", Bot, "Follow"],
              ] as const).map(([m, Icon, label]) => (
                <button
                  key={m}
                  disabled={!online}
                  onClick={() => setMode(m)}
                  className={`flex flex-col items-center gap-1 rounded-xl border px-2 py-3 text-sm transition disabled:opacity-50 ${
                    status?.mode === m ? "bg-forest-600 border-transparent" : "bg-white/80 text-forest-800 hover:bg-forest-100"
                  }`}
                >
                  <Icon className="h-5 w-5" />
                  {label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-gray-500">Follow: the rover tracks the nearest detected cow. Driving switches to manual.</p>
          </Card>

          <Card>
            <h2 className="mb-3 text-xl font-semibold text-forest-800">Drive</h2>
            <div className="mx-auto grid max-w-[200px] grid-cols-3 gap-2">
              <span />
              <PadButton dir="forward" held={held} start={start} release={release} disabled={!online}>
                <ArrowUp className="mx-auto h-6 w-6" />
              </PadButton>
              <span />
              <PadButton dir="left" held={held} start={start} release={release} disabled={!online}>
                <ArrowLeft className="mx-auto h-6 w-6" />
              </PadButton>
              <button
                onClick={() => start("stop")}
                disabled={!online}
                className="rounded-xl bg-red-600 p-3 text-white shadow hover:bg-red-700 disabled:opacity-50"
                aria-label="Stop"
              >
                <OctagonX className="mx-auto h-6 w-6" />
              </button>
              <PadButton dir="right" held={held} start={start} release={release} disabled={!online}>
                <ArrowRight className="mx-auto h-6 w-6" />
              </PadButton>
              <span />
              <PadButton dir="backward" held={held} start={start} release={release} disabled={!online}>
                <ArrowDown className="mx-auto h-6 w-6" />
              </PadButton>
              <span />
            </div>
            <label className="mt-4 block text-sm text-forest-800">
              Speed {speed}%
              <input type="range" min={10} max={100} step={5} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="w-full" />
            </label>
            <p className="mt-2 text-xs text-gray-500">Hold a button (or W/A/S/D) to drive; release to stop. Space stops.</p>
          </Card>

          <Card>
            <h2 className="mb-3 text-xl font-semibold text-forest-800">Sensors</h2>
            <dl className="grid grid-cols-2 gap-y-1 text-sm">
              <dt className="text-gray-500">Obstacle</dt>
              <dd className={`tabular-nums ${dist != null && dist < (status?.stop_cm ?? 20) ? "font-semibold text-red-700" : ""}`}>
                {dist == null ? "no echo" : `${dist.toFixed(0)} cm`}
              </dd>
              <dt className="text-gray-500">Battery</dt>
              <dd className={`tabular-nums ${status?.battery != null && status.battery < 9.5 ? "text-red-700" : ""}`}>
                {fmt(status?.battery, 2, " V")}
              </dd>
              <dt className="text-gray-500">Motors L / R</dt>
              <dd className="tabular-nums">{status ? `${status.left_dps.toFixed(0)} / ${status.right_dps.toFixed(0)} °/s` : "—"}</dd>
              <dt className="text-gray-500">In view</dt>
              <dd className="tabular-nums">
                {status?.seen && Object.keys(status.seen).length
                  ? Object.entries(status.seen)
                      .map(([label, n]) => `${n} ${label}`)
                      .join(", ")
                  : status
                    ? "nothing"
                    : "—"}
              </dd>
            </dl>
          </Card>
        </div>
      </div>
    </Page>
  );
}

function PadButton({ dir, held, start, release, disabled, children }: {
  dir: Direction;
  held: Direction | null;
  start: (d: Direction) => void;
  release: () => void;
  disabled: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      disabled={disabled}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        start(dir);
      }}
      onPointerUp={release}
      onPointerCancel={release}
      aria-label={dir}
      className={`select-none touch-none rounded-xl border p-3 shadow-sm transition disabled:opacity-50 ${
        held === dir ? "bg-forest-600 border-transparent" : "bg-white/80 text-forest-800 hover:bg-forest-100"
      }`}
    >
      {children}
    </button>
  );
}
