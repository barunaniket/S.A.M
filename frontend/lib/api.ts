import { clearToken, getToken } from "./auth";
import type { Envelope } from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type FetchOpts = RequestInit & { auth?: boolean };

class ApiError extends Error {
  status: number;
  code?: string | null;
  constructor(message: string, status: number, code?: string | null) {
    super(message);
    this.status = status;
    this.code = code ?? null;
  }
}

export async function apiFetch<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const headers = new Headers(opts.headers);
  if (!headers.has("Content-Type") && opts.body) {
    headers.set("Content-Type", "application/json");
  }

  const token = getToken();
  if (opts.auth !== false && token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError("Session expired", 401);
  }

  let body: unknown = null;
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    body = await res.json();
  } else {
    body = await res.text();
  }

  if (!res.ok) {
    const msg =
      (body as { detail?: string } | null)?.detail ??
      (body as { message?: string } | null)?.message ??
      `Request failed (${res.status})`;
    throw new ApiError(msg, res.status);
  }

  // Worker-protocol envelope detection: presence of `success` key.
  if (
    body &&
    typeof body === "object" &&
    "success" in (body as Record<string, unknown>)
  ) {
    const env = body as Envelope<T>;
    if (!env.success) {
      throw new ApiError(
        env.message ?? "Backend reported failure",
        res.status,
        env.error_code,
      );
    }
    return env.data as T;
  }

  // Flat response (e.g. /auth/callback returns {token, user, message}).
  return body as T;
}

export { ApiError };
