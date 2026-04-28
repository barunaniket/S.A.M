"use client";

import useSWR from "swr";
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { FileDropZone } from "@/components/common/FileDropZone";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";

type AcademicEvent = {
  id: number;
  kind: "HOLIDAY" | "EXAM" | "BREAK" | "EVENT";
  title: string;
  start_date: string;
  end_date: string;
};

type ParsedEvent = Omit<AcademicEvent, "id">;

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const KINDS: AcademicEvent["kind"][] = ["HOLIDAY", "EXAM", "BREAK", "EVENT"];

const kindClass: Record<AcademicEvent["kind"], string> = {
  HOLIDAY: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  EXAM: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  BREAK: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  EVENT: "bg-muted text-foreground",
};

async function uploadCalendarFile(file: File): Promise<{
  events: ParsedEvent[];
  needs_review: boolean;
  pending_id: number;
}> {
  const fd = new FormData();
  fd.append("file", file);
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1/academic/upload`, {
    method: "POST",
    body: fd,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  const body = await res.json();
  if (!res.ok || !body?.success) {
    throw new Error(body?.detail ?? body?.message ?? "Upload failed");
  }
  return body;
}

function CalendarPanelInner() {
  const { data, mutate } = useSWR<{ events: AcademicEvent[] }>(
    "/api/v1/academic/events",
    (path: string) => apiFetch(path),
  );
  const events = data?.events ?? [];

  const [pending, setPending] = useState<ParsedEvent[]>([]);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blank: ParsedEvent = {
    kind: "HOLIDAY",
    title: "",
    start_date: new Date().toISOString().slice(0, 10),
    end_date: new Date().toISOString().slice(0, 10),
  };

  const onFile = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const res = await uploadCalendarFile(file);
      setPendingId(res.pending_id);
      setPending(res.events);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const updatePending = (idx: number, patch: Partial<ParsedEvent>) =>
    setPending((p) => p.map((e, i) => (i === idx ? { ...e, ...patch } : e)));

  const removePending = (idx: number) =>
    setPending((p) => p.filter((_, i) => i !== idx));

  const addPendingRow = () => setPending((p) => [...p, blank]);

  const savePending = async () => {
    if (!pending.length) return;
    setBusy(true);
    setError(null);
    try {
      const path = pendingId
        ? `/api/v1/academic/confirm/${pendingId}`
        : `/api/v1/academic/manual`;
      await apiFetch<{ saved: number }>(path, {
        method: "POST",
        body: JSON.stringify({ events: pending, replace_overlapping: false }),
      });
      setPending([]);
      setPendingId(null);
      mutate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const deleteEvent = async (id: number) => {
    try {
      await apiFetch(`/api/v1/academic/events/${id}`, { method: "DELETE" });
      mutate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Academic calendar</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload the year&apos;s calendar (PDF / Excel / Word) or add events
          one at a time. Holidays and exam windows automatically block
          meeting scheduling.
        </p>
      </header>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </Card>
      )}

      {/* ---------------- Upload zone ---------------- */}
      {pending.length === 0 && (
        <FileDropZone onFile={onFile} disabled={busy} hint="Drop the calendar file here" />
      )}

      {/* ---------------- Pending review ---------------- */}
      {pending.length > 0 && (
        <Card className="overflow-hidden">
          <div className="border-b border-border bg-muted/30 px-4 py-2 text-sm font-medium">
            Review the parsed events before saving
          </div>
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted-foreground">
              <tr>
                <th className="p-2 text-left">Kind</th>
                <th className="p-2 text-left">Title</th>
                <th className="p-2 text-left">Start</th>
                <th className="p-2 text-left">End</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {pending.map((e, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="p-2">
                    <select
                      value={e.kind}
                      onChange={(ev) =>
                        updatePending(i, { kind: ev.target.value as AcademicEvent["kind"] })
                      }
                      className="rounded border bg-background px-2 py-1"
                    >
                      {KINDS.map((k) => (
                        <option key={k} value={k}>
                          {k}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="p-2">
                    <input
                      value={e.title}
                      onChange={(ev) => updatePending(i, { title: ev.target.value })}
                      className="w-full rounded border bg-background px-2 py-1"
                    />
                  </td>
                  <td className="p-2">
                    <input
                      type="date"
                      value={e.start_date}
                      onChange={(ev) =>
                        updatePending(i, { start_date: ev.target.value })
                      }
                      className="rounded border bg-background px-2 py-1"
                    />
                  </td>
                  <td className="p-2">
                    <input
                      type="date"
                      value={e.end_date}
                      onChange={(ev) => updatePending(i, { end_date: ev.target.value })}
                      className="rounded border bg-background px-2 py-1"
                    />
                  </td>
                  <td className="p-2 text-right">
                    <button
                      onClick={() => removePending(i)}
                      className="text-xs text-destructive hover:underline"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex flex-wrap items-center gap-2 border-t border-border p-3">
            <Button variant="outline" onClick={addPendingRow} disabled={busy}>
              Add row
            </Button>
            <Button onClick={savePending} disabled={busy || pending.length === 0}>
              {busy ? "Saving…" : `Save ${pending.length} event(s)`}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setPending([]);
                setPendingId(null);
              }}
              disabled={busy}
            >
              Cancel
            </Button>
          </div>
        </Card>
      )}

      <div className="flex justify-end">
        <Button
          variant="outline"
          onClick={() => setPending([blank])}
          disabled={busy || pending.length > 0}
        >
          Add manually
        </Button>
      </div>

      {/* ---------------- Existing events ---------------- */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Saved events ({events.length})
        </h2>
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No events yet.</p>
        ) : (
          <Card className="divide-y divide-border">
            {events.map((e) => (
              <div key={e.id} className="flex items-center gap-3 p-3 text-sm">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ${kindClass[e.kind]}`}
                >
                  {e.kind}
                </span>
                <span className="flex-1 font-medium">{e.title}</span>
                <span className="text-xs text-muted-foreground">
                  {e.start_date}
                  {e.end_date !== e.start_date ? ` → ${e.end_date}` : ""}
                </span>
                <button
                  onClick={() => deleteEvent(e.id)}
                  className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                  title="Delete"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            ))}
          </Card>
        )}
      </section>
    </div>
  );
}

export default function CalendarPage() {
  return (
    <RoleGuard allow={["SUPER_ADMIN"]}>
      <CalendarPanelInner />
    </RoleGuard>
  );
}
