"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

type Status =
  | "init"
  | "posting"
  | "saving"
  | "redirecting"
  | "onboarded"
  | "error";

// Module-level dedupe so React strict mode's double-mount doesn't try to
// exchange the same single-use Google code twice.
const processedCodes = new Set<string>();

function CallbackInner() {
  const params = useSearchParams();
  const [status, setStatus] = useState<Status>("init");
  const [detail, setDetail] = useState<string>("Reading callback parameters…");

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state") ?? undefined;
    const oauthError = params.get("error");

    if (oauthError) {
      setStatus("error");
      setDetail(`Google denied the request: ${oauthError}`);
      return;
    }

    if (!code) {
      setStatus("error");
      setDetail("Missing OAuth code in the callback URL.");
      return;
    }

    if (processedCodes.has(code)) return;
    processedCodes.add(code);

    (async () => {
      try {
        setStatus("posting");
        setDetail(`POST ${API_BASE}/auth/callback`);

        const res = await fetch(`${API_BASE}/auth/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, state }),
        });

        const text = await res.text();
        let data: {
          token?: string;
          user?: { name?: string; email?: string; role?: string };
          onboarded?: boolean;
          channel?: string;
          detail?: unknown;
        } = {};
        try {
          data = JSON.parse(text);
        } catch {
          /* keep raw text in `text` */
        }

        if (!res.ok) {
          setStatus("error");
          setDetail(
            `Backend returned ${res.status}\n` +
              (typeof data.detail === "string"
                ? data.detail
                : text || res.statusText),
          );
          return;
        }

        // Chat-first onboarding response: no JWT, no SPA redirect.
        // Show a "return to Telegram" success page.
        if (data.onboarded) {
          setStatus("onboarded");
          const handle = data.user?.name ?? data.user?.email ?? "there";
          const channel = (data.channel ?? "telegram").replace(/^./, (c) => c.toUpperCase());
          setDetail(
            `${handle} — you're all set. Return to ${channel} to continue setting up.`,
          );
          return;
        }

        if (!data.token || !data.user) {
          setStatus("error");
          setDetail(
            `Backend response missing token/user.\nRaw response:\n${text}`,
          );
          return;
        }

        setStatus("saving");
        setDetail("Storing session…");
        window.localStorage.setItem("sam_jwt", data.token);
        window.localStorage.setItem("sam_user", JSON.stringify(data.user));

        setStatus("redirecting");
        setDetail("Redirecting to dashboard…");
        // Use a hard navigation rather than the Next router so the new
        // localStorage state is read fresh by the dashboard layout.
        window.location.replace("/app");
      } catch (err) {
        setStatus("error");
        setDetail(
          `Network error talking to ${API_BASE}\n` +
            (err instanceof Error ? err.message : String(err)) +
            `\n\nIs the backend reachable from your browser? Try opening ${API_BASE}/ in a new tab.`,
        );
      }
    })();
  }, [params]);

  const isError = status === "error";
  const isOnboarded = status === "onboarded";

  return (
    <main className="grid min-h-screen place-items-center px-6">
      <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-8 text-center shadow-sm">
        {isError ? (
          <>
            <h2 className="text-lg font-semibold text-destructive">
              Sign-in failed
            </h2>
            <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-left text-xs text-muted-foreground">
              {detail}
            </pre>
            <a
              href="/login"
              className="mt-6 inline-block text-sm font-medium underline"
            >
              Back to login
            </a>
          </>
        ) : isOnboarded ? (
          <>
            <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600">
              <svg
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold">You&apos;re linked</h2>
            <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
            <p className="mt-6 text-xs text-muted-foreground">
              You can close this tab.
            </p>
          </>
        ) : (
          <>
            <div className="mx-auto mb-4 flex justify-center">
              <span className="size-2 animate-bounce rounded-full bg-foreground [animation-delay:-0.3s]" />
              <span className="mx-1 size-2 animate-bounce rounded-full bg-foreground [animation-delay:-0.15s]" />
              <span className="size-2 animate-bounce rounded-full bg-foreground" />
            </div>
            <h2 className="text-base font-medium">Connecting your calendar…</h2>
            <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
            <p className="mt-2 text-[10px] uppercase tracking-widest text-muted-foreground">
              {status}
            </p>
          </>
        )}
      </div>
    </main>
  );
}

export default function CallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="grid min-h-screen place-items-center px-6">
          <p className="text-sm text-muted-foreground">Loading callback…</p>
        </main>
      }
    >
      <CallbackInner />
    </Suspense>
  );
}
