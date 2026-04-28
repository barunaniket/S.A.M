"use client";

import { useState } from "react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { FileDropZone } from "@/components/common/FileDropZone";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";

type Entry = {
  day_of_week: number;
  start_time: string;
  end_time: string;
  subject?: string | null;
  room?: string | null;
  batch?: string | null;
};

type UploadResponse = {
  success: boolean;
  pending_id: number;
  kind: string;
  entries: Entry[];
  needs_review: boolean;
  summary: string;
  ocr_confidence?: number | null;
};

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function uploadTimetableFile(file: File): Promise<UploadResponse> {
  const fd = new FormData();
  fd.append("file", file);
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1/timetable/upload`, {
    method: "POST",
    body: fd,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  const body = await res.json();
  if (!res.ok || !body?.success) {
    throw new Error(body?.detail ?? body?.message ?? "Upload failed");
  }
  return body as UploadResponse;
}

function TimetableUploadInner() {
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [needsReview, setNeedsReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const onFile = async (file: File) => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const result = await uploadTimetableFile(file);
      setPendingId(result.pending_id);
      setEntries(result.entries ?? []);
      setNeedsReview(result.needs_review);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const updateEntry = (idx: number, patch: Partial<Entry>) => {
    setEntries((prev) => prev.map((e, i) => (i === idx ? { ...e, ...patch } : e)));
  };

  const removeEntry = (idx: number) => {
    setEntries((prev) => prev.filter((_, i) => i !== idx));
  };

  const addEntry = () => {
    setEntries((prev) => [
      ...prev,
      { day_of_week: 0, start_time: "09:00", end_time: "10:00" },
    ]);
  };

  const onConfirm = async () => {
    if (!pendingId) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch<{ saved: number }>(
        `/api/v1/timetable/confirm/${pendingId}`,
        {
          method: "POST",
          body: JSON.stringify({ entries }),
        },
      );
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const onReset = () => {
    setPendingId(null);
    setEntries([]);
    setNeedsReview(false);
    setDone(false);
    setError(null);
  };

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">My timetable</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Send a photo, a voice note, or paste your weekly schedule. Students
          can then ask S.A.M. where you are or when you&apos;re free.
        </p>
      </header>

      {!pendingId && !done && (
        <FileDropZone onFile={onFile} disabled={busy} />
      )}

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </Card>
      )}

      {busy && !pendingId && (
        <p className="text-sm text-muted-foreground">
          Parsing… (image OCR or audio transcription may take a few seconds.)
        </p>
      )}

      {pendingId && entries.length > 0 && !done && (
        <>
          {needsReview && (
            <Card className="border-amber-500/40 bg-amber-500/5 p-3 text-xs">
              Some cells looked ambiguous — please review carefully before
              saving.
            </Card>
          )}

          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="p-2 text-left">Day</th>
                  <th className="p-2 text-left">Start</th>
                  <th className="p-2 text-left">End</th>
                  <th className="p-2 text-left">Subject</th>
                  <th className="p-2 text-left">Room</th>
                  <th className="p-2 text-left">Batch</th>
                  <th className="p-2"></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr key={i} className="border-t border-border">
                    <td className="p-2">
                      <select
                        value={e.day_of_week}
                        onChange={(ev) =>
                          updateEntry(i, {
                            day_of_week: Number(ev.target.value),
                          })
                        }
                        className="rounded border bg-background px-2 py-1"
                      >
                        {DAY_NAMES.map((d, idx) => (
                          <option key={d} value={idx}>
                            {d}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="p-2">
                      <input
                        type="time"
                        value={e.start_time}
                        onChange={(ev) =>
                          updateEntry(i, { start_time: ev.target.value })
                        }
                        className="rounded border bg-background px-2 py-1"
                      />
                    </td>
                    <td className="p-2">
                      <input
                        type="time"
                        value={e.end_time}
                        onChange={(ev) =>
                          updateEntry(i, { end_time: ev.target.value })
                        }
                        className="rounded border bg-background px-2 py-1"
                      />
                    </td>
                    <td className="p-2">
                      <input
                        value={e.subject ?? ""}
                        onChange={(ev) =>
                          updateEntry(i, { subject: ev.target.value })
                        }
                        className="w-full rounded border bg-background px-2 py-1"
                      />
                    </td>
                    <td className="p-2">
                      <input
                        value={e.room ?? ""}
                        onChange={(ev) =>
                          updateEntry(i, { room: ev.target.value })
                        }
                        className="w-full rounded border bg-background px-2 py-1"
                      />
                    </td>
                    <td className="p-2">
                      <input
                        value={e.batch ?? ""}
                        onChange={(ev) =>
                          updateEntry(i, { batch: ev.target.value })
                        }
                        className="w-full rounded border bg-background px-2 py-1"
                      />
                    </td>
                    <td className="p-2 text-right">
                      <button
                        onClick={() => removeEntry(i)}
                        className="text-xs text-destructive hover:underline"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={addEntry} disabled={busy}>
              Add row
            </Button>
            <Button onClick={onConfirm} disabled={busy || entries.length === 0}>
              {busy ? "Saving…" : `Save timetable (${entries.length} class${entries.length === 1 ? "" : "es"})`}
            </Button>
            <Button variant="ghost" onClick={onReset} disabled={busy}>
              Cancel
            </Button>
          </div>
        </>
      )}

      {done && (
        <Card className="border-emerald-500/40 bg-emerald-500/5 p-4 text-sm">
          Timetable saved. Students can now ask S.A.M. about your schedule.
          <div className="mt-3">
            <Button variant="outline" onClick={onReset}>
              Upload another
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

export default function TimetableUploadPage() {
  return (
    <RoleGuard allow={["FACULTY", "ADMIN"]}>
      <TimetableUploadInner />
    </RoleGuard>
  );
}
