import type { ReactNode } from "react";
import type { Status } from "../api";
import { STATUS_STYLE } from "../format";

export function Page({ title, subtitle, actions, children }: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-hero-gradient pt-28 pb-16">
      <div className="mx-auto max-w-6xl px-4">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-forest-800 md:text-4xl">{title}</h1>
            {subtitle && <p className="mt-1 text-[hsl(var(--muted-foreground))]">{subtitle}</p>}
          </div>
          {actions}
        </div>
        {children}
      </div>
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card-glass rounded-2xl p-5 shadow-sm ${className}`}>{children}</div>;
}

export function StatusChip({ status }: { status: Status }) {
  const s = STATUS_STYLE[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${s.chip}`}>
      <span className={`h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

export function Stat({ label, value, hint, tone = "" }: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: string;
}) {
  return (
    <Card>
      <div className="text-sm text-[hsl(var(--muted-foreground))]">{label}</div>
      <div className={`mt-1 text-3xl font-semibold tabular-nums text-forest-800 ${tone}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">{hint}</div>}
    </Card>
  );
}

export function LiveDot({ state }: { state: "connecting" | "live" | "offline" }) {
  const color = state === "live" ? "bg-emerald-500" : state === "connecting" ? "bg-amber-400" : "bg-gray-400";
  const label = state === "live" ? "Live" : state === "connecting" ? "Connecting" : "Reconnecting";
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-sm text-forest-800 shadow-sm">
      <span className={`h-2.5 w-2.5 rounded-full ${color} ${state === "live" ? "animate-pulse" : ""}`} />
      {label}
    </span>
  );
}

export function ErrorNote({ text }: { text: string | null }) {
  if (!text) return null;
  return <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{text}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-[hsl(var(--muted-foreground))]">{children}</div>;
}
