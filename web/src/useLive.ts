import { useEffect, useRef, useState } from "react";
import { wsUrl } from "./api";

export type LiveMessage =
  | ({ type: "vitals" } & Record<string, unknown>)
  | ({ type: "env" } & Record<string, unknown>)
  | ({ type: "alert" } & Record<string, unknown>)
  | ({ type: "rover_status" } & Record<string, unknown>)
  | { type: "hello" };

/**
 * Subscribe to the API's live WebSocket. Reconnects with backoff.
 * `onMessage` is kept in a ref so callers can pass an inline function.
 */
export function useLive(onMessage: (m: LiveMessage) => void): "connecting" | "live" | "offline" {
  const [state, setState] = useState<"connecting" | "live" | "offline">("connecting");
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      setState("connecting");
      ws = new WebSocket(wsUrl("/ws/live"));
      ws.onopen = () => {
        retry = 0;
        setState("live");
      };
      ws.onmessage = (ev) => {
        try {
          handler.current(JSON.parse(ev.data));
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setState("offline");
        retry = Math.min(retry + 1, 6);
        timer = window.setTimeout(connect, 500 * 2 ** retry);
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return state;
}
