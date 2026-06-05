import type { WsNotification } from "./types";
import { getToken } from "./auth";

const WS_BASE =
  process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:8000";

export function openNotificationsSocket(
  userId: number | string,
  onMessage: (msg: WsNotification) => void,
): WebSocket {
  // Browsers can't set an Authorization header on a WebSocket, so the JWT
  // rides in the query string. The server rejects a missing/mismatched token.
  const token = getToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  const ws = new WebSocket(`${WS_BASE}/api/v1/ws/notifications/${userId}${qs}`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as WsNotification;
      onMessage(data);
    } catch {
      onMessage({ message: String(event.data), type: "info" });
    }
  };

  return ws;
}
