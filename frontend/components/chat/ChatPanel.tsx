"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { apiFetch, ApiError } from "@/lib/api";
import { openNotificationsSocket } from "@/lib/ws";
import { useAuth } from "@/hooks/useAuth";
import type { ProcessExecuteResponse } from "@/lib/types";
import { Composer } from "./Composer";
import { MessageBubble, type ChatMessage } from "./MessageBubble";
import { LoadingDots } from "@/components/common/LoadingDots";

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

function formatResult(res: ProcessExecuteResponse): { content: string; intent?: string } {
  const intent =
    typeof res?.intent === "object" && res.intent
      ? (res.intent as { type?: string }).type
      : undefined;

  const result = res?.result as Record<string, unknown> | null | undefined;
  if (result && typeof result === "object") {
    if (typeof result.message === "string") return { content: result.message, intent };
    if (typeof result.summary === "string") return { content: result.summary, intent };
  }

  if (intent === "clarification_needed") {
    return {
      content:
        (result as { question?: string } | undefined)?.question ??
        "I need a bit more info — could you clarify?",
      intent,
    };
  }

  return {
    content: "Done.\n\n" + JSON.stringify(res?.result ?? {}, null, 2),
    intent,
  };
}

export function ChatPanel() {
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: uid(),
      role: "assistant",
      content:
        "Hi! Tell me what to schedule, who to invite, or what to broadcast — I'll handle the rest.",
    },
  ]);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, busy]);

  // WebSocket — incoming reminders/notifications
  useEffect(() => {
    if (!user?.id) return;
    let socket: WebSocket | null = null;
    try {
      socket = openNotificationsSocket(user.id, (notif) => {
        setMessages((prev) => [
          ...prev,
          {
            id: uid(),
            role: "system",
            content: `${notif.type ? `[${notif.type}] ` : ""}${notif.message}`,
          },
        ]);
      });
    } catch (err) {
      console.warn("WebSocket failed", err);
    }
    return () => {
      socket?.close();
    };
  }, [user?.id]);

  async function handleSubmit(text: string) {
    const userMsg: ChatMessage = { id: uid(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setBusy(true);
    try {
      const res = await apiFetch<ProcessExecuteResponse>(
        "/api/v1/process/execute",
        {
          method: "POST",
          body: JSON.stringify({ user_input: text }),
        },
      );
      const { content, intent } = formatResult(res);
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: "assistant", content, meta: { intent, raw: res } },
      ]);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : "Something went wrong talking to S.A.M.";
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: "assistant",
          content: `⚠ ${msg}`,
        },
      ]);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-3">
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {busy && (
            <div className="flex">
              <div className="rounded-2xl rounded-bl-sm bg-muted px-4 py-3">
                <LoadingDots />
              </div>
            </div>
          )}
        </div>
      </div>
      <Composer onSubmit={handleSubmit} disabled={busy} />
    </div>
  );
}
