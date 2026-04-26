export type SamUser = {
  id: number;
  name: string;
  email: string;
  picture?: string | null;
  role?: string | null;
};

export type AuthCallbackResponse = {
  message: string;
  token: string;
  user: SamUser;
};

export type LoginUrlResponse = {
  url: string;
};

export type Envelope<T> = {
  success: boolean;
  data: T | null;
  message?: string | null;
  error_code?: string | null;
};

export type GoogleStatus = {
  connected: boolean;
  reason?: "no_token" | "expired";
  email?: string;
};

export type AgendaMeeting = {
  id?: string | number;
  title?: string;
  start?: string;
  end?: string;
  meet_link?: string;
  attendees?: Array<{ email?: string; name?: string }>;
};

export type AgendaResponse = {
  meetings: AgendaMeeting[];
  conflicts?: unknown[];
  suggestions?: unknown[];
};

export type ProcessExecuteResponse = {
  intent: { type?: string; [k: string]: unknown };
  result: { [k: string]: unknown } | null;
};

export type WsNotification = {
  message: string;
  type: "invite" | "update" | "cancel" | "reminder" | string;
};
