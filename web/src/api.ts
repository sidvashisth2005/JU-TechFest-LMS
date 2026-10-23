import axios from "axios";

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "lms_token";

export const api = axios.create({ baseURL: BASE, timeout: 15000 });

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) - the session just won't persist */
  }
}

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401 && !String(error.config?.url).includes("/auth/login")) {
      setToken(null);
      window.dispatchEvent(new Event("lms:logout"));
    }
    return Promise.reject(error);
  },
);

/** URL for things that can't send headers (<img> video stream): token goes in the query. */
export function authedUrl(path: string): string {
  const token = getToken();
  return `${BASE}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token ?? "")}`;
}

export function wsUrl(path: string): string {
  const origin = BASE || window.location.origin;
  return authedUrl(path).replace(BASE, origin.replace(/^http/, "ws"));
}

export function errorText(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const detail = e.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (e.code === "ECONNABORTED") return "Server took too long to answer";
    if (!e.response) return "Cannot reach the server";
    return `Request failed (${e.response.status})`;
  }
  return String(e);
}

// ---------- shared types (mirror backend/api/routes.py) ----------
export type Severity = "info" | "warning" | "critical";
export type Status = Severity | "ok";

export interface AnimalRow {
  animal_id: string;
  name: string | null;
  breed: string | null;
  last_seen: number | null;
  online: boolean;
  hr: number | null;
  spo2: number | null;
  body_temp: number | null;
  activity: number | null;
  battery: number | null;
  status: Status;
  open_alerts: number;
}

export interface Alert {
  id: number;
  ts: number;
  kind: string;
  severity: Severity;
  message: string;
  animal_id: string | null;
  station_id: string | null;
  value: number | null;
  source: string;
  acked_at?: number | null;
  acked_by?: string | null;
}

export interface EnvPoint {
  station_id: string;
  ts: number;
  temp: number | null;
  humidity: number | null;
  pressure: number | null;
  thi: number | null;
}

export interface Summary {
  animals: number;
  online: number;
  open_alerts: Partial<Record<Severity, number>>;
  environment: EnvPoint[];
}

export interface HistoryPoint {
  ts: number;
  hr: number | null;
  spo2: number | null;
  body_temp: number | null;
  activity: number | null;
  steps: number | null;
}
