import type { ServerEvent } from "./types";

export type SendInput = (value: unknown) => void;

export function connectSession(
  sessionId: string,
  onEvent: (ev: ServerEvent) => void,
  onOpen?: () => void,
  onClose?: () => void,
): { send: SendInput; close: () => void } {
  // WebSockets can't be proxied by Next.js rewrites in dev, so connect
  // directly to the backend on its own port.
  const base =
    process.env.NEXT_PUBLIC_WS_BASE ||
    (typeof window !== "undefined"
      ? `ws://${window.location.hostname}:8001`
      : "ws://localhost:8001");
  const url = `${base}/ws/${sessionId}`;
  const ws = new WebSocket(url);

  ws.onopen = () => onOpen?.();
  ws.onclose = () => onClose?.();
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as ServerEvent;
      onEvent(data);
    } catch {}
  };

  return {
    send: (value) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "user.input", value }));
      }
    },
    close: () => ws.close(),
  };
}

// HTTP API calls go through the Next.js dev rewrite (see next.config.js),
// so a relative path keeps the browser on the same origin and avoids CORS.
export const API_BASE = "";
