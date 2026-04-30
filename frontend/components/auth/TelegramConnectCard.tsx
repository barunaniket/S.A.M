"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { apiFetch } from "@/lib/api";
import type { TelegramPairResponse } from "@/lib/types";
import { useTelegramStatus } from "@/hooks/useTelegramStatus";

export function TelegramConnectCard() {
  const { data, isLoading, mutate } = useTelegramStatus();
  const [pairing, setPairing] = useState<TelegramPairResponse | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleGenerate() {
    setBusy(true);
    try {
      const resp = await apiFetch<TelegramPairResponse>(
        "/api/v1/me/telegram/pair",
        { method: "POST" },
      );
      setPairing(resp);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Couldn't generate a code",
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleUnlink() {
    setBusy(true);
    try {
      await apiFetch("/api/v1/me/telegram", { method: "DELETE" });
      setPairing(null);
      await mutate();
      toast.success("Telegram unlinked");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Couldn't unlink",
      );
    } finally {
      setBusy(false);
    }
  }

  async function copyCode(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      toast.success("Code copied");
    } catch {
      // ignore — user can still read it on screen
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2">
            <TelegramIcon />
            Telegram
          </CardTitle>
          <StatusBadge
            isLoading={isLoading}
            configured={data?.configured ?? true}
            linked={data?.linked ?? false}
          />
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {!data?.configured && (
          <p className="text-sm text-muted-foreground">
            The Telegram bot isn&apos;t configured on the server yet. Ask an
            admin to set <code className="text-xs">TELEGRAM_BOT_TOKEN</code> and
            run the poller.
          </p>
        )}

        {data?.configured && data?.linked && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Linked to Telegram
              {data.username ? (
                <>
                  {" "}as{" "}
                  <span className="font-medium text-foreground">
                    @{data.username}
                  </span>
                </>
              ) : null}
              . You can DM the bot to schedule meetings, run broadcasts, or
              upload your timetable.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={handleUnlink}
              disabled={busy}
            >
              {busy ? "Unlinking…" : "Disconnect Telegram"}
            </Button>
          </div>
        )}

        {data?.configured && !data?.linked && !pairing && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Generate a one-time code, then DM it to the SAM bot to link this
              account. The code expires in 5 minutes.
            </p>
            <Button onClick={handleGenerate} disabled={busy}>
              {busy ? "Generating…" : "Connect Telegram"}
            </Button>
          </div>
        )}

        {data?.configured && !data?.linked && pairing && (
          <div className="space-y-3">
            <div className="flex items-center justify-center rounded-md border bg-muted/40 px-4 py-6">
              <button
                type="button"
                onClick={() => copyCode(pairing.code)}
                className="font-mono text-3xl tracking-widest text-foreground hover:opacity-80"
                title="Click to copy"
              >
                {pairing.code}
              </button>
            </div>

            {pairing.deep_link ? (
              <p className="text-sm text-muted-foreground">
                On mobile, tap to open:{" "}
                <a
                  href={pairing.deep_link}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary underline"
                >
                  {pairing.deep_link.replace("https://", "")}
                </a>
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                Open Telegram, find the SAM bot, and send{" "}
                <code className="rounded bg-muted px-1 py-0.5">
                  /start {pairing.code}
                </code>
                .
              </p>
            )}

            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                Code expires in {pairing.ttl_minutes} minutes.
              </p>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleGenerate}
                disabled={busy}
              >
                {busy ? "…" : "Regenerate"}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StatusBadge({
  isLoading,
  configured,
  linked,
}: {
  isLoading: boolean;
  configured: boolean;
  linked: boolean;
}) {
  if (isLoading) {
    return <Badge variant="outline">Checking…</Badge>;
  }
  if (!configured) {
    return <Badge variant="outline">Not configured</Badge>;
  }
  if (linked) {
    return <Badge variant="success">Linked</Badge>;
  }
  return <Badge variant="warning">Not linked</Badge>;
}

function TelegramIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      aria-hidden
      className="text-[#229ED9]"
    >
      <path
        fill="currentColor"
        d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.24 3.64 11.94c-.88-.27-.89-.88.2-1.3l16-6.18c.73-.27 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.7l-4.13-3.05-2 1.93c-.23.23-.42.42-.86.42z"
      />
    </svg>
  );
}
