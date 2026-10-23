import type { Severity, Status } from "./api";

export const fmt = (v: number | null | undefined, digits = 1, unit = "") =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v.toFixed(digits)}${unit}`;

export function ago(ts: number | null | undefined): string {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const timeOfDay = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const dateTime = (ts: number) =>
  new Date(ts * 1000).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

export const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const STATUS_STYLE: Record<Status, { dot: string; chip: string; label: string }> = {
  ok: { dot: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-800 border-emerald-200", label: "Healthy" },
  info: { dot: "bg-sky-500", chip: "bg-sky-50 text-sky-800 border-sky-200", label: "Note" },
  warning: { dot: "bg-amber-500", chip: "bg-amber-50 text-amber-900 border-amber-300", label: "Watch" },
  critical: { dot: "bg-red-600", chip: "bg-red-50 text-red-800 border-red-300", label: "Critical" },
};

export const SEVERITY_ORDER: Severity[] = ["critical", "warning", "info"];

/** Cattle heat-stress bands for the temperature-humidity index. */
export function thiBand(thi: number | null | undefined): { label: string; className: string } {
  if (thi === null || thi === undefined) return { label: "No data", className: "text-gray-500" };
  if (thi >= 89) return { label: "Severe stress", className: "text-red-700" };
  if (thi >= 79) return { label: "Moderate stress", className: "text-orange-600" };
  if (thi >= 72) return { label: "Mild stress", className: "text-amber-600" };
  return { label: "Comfortable", className: "text-emerald-700" };
}

/** Dew point in °C (Magnus formula); same as common.schemas.dew_point. */
export function dewPoint(temp: number | null | undefined, rh: number | null | undefined): number | null {
  if (temp === null || temp === undefined || rh === null || rh === undefined || rh <= 0) return null;
  const a = 17.62;
  const b = 243.12;
  const g = Math.log(rh / 100) + (a * temp) / (b + temp);
  return Math.round(((b * g) / (a - g)) * 10) / 10;
}

export function compassLabel(heading: number | null | undefined): string {
  if (heading === null || heading === undefined) return "—";
  return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.floor((((heading % 360) + 360) % 360 + 22.5) / 45) % 8];
}
