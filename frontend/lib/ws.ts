import type { WsNotification } from "./types";

const WS_BASE =
  process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:8000";

export function openNotificationsSocket(
  userId: number | string,
  onMessage: (msg: WsNotification) => void,
): WebSocket {
  const ws = new WebSocket(`${WS_BASE}/api/v1/ws/notifications/${userId}`);

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
