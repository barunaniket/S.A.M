"use client";

import { useState } from "react";
import useSWR from "swr";
import { CheckCircle2, XCircle } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";

type Row = {
  id: number;
  user_id: number;
  full_name: string;
  batch?: string | null;
  status: "PRESENT" | "ABSENT";
  score?: number | null;
  source?: string | null;
  overridden?: boolean;
  class_date: string;
};

type Sheet = {
  subject: string;
  batch?: string | null;
  class_date: string;
  total: number;
  present: Row[];
  absent: Row[];
};

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

function AttendanceInner() {
  const [subject, setSubject] = useState("");
  const [batch, setBatch] = useState("");
  const [date, setDate] = useState<string>(isoToday());
  const [submitted, setSubmitted] = useState(false);

  const params = new URLSearchParams();
  if (subject) params.set("subject", subject);
  if (batch) params.set("batch", batch);
  if (date) params.set("date", date);
  const qs = params.toString();

  const { data, isLoading, mutate, error } = useSWR<Sheet>(
    submitted && subject ? `/api/v1/attendance?${qs}` : null,
    (path: string) => apiFetch<Sheet>(path),
  );

  const onOverride = async (row: Row) => {
    const target = row.status === "PRESENT" ? "ABSENT" : "PRESENT";
    if (!confirm(`Mark ${row.full_name} as ${target}?`)) return;
    await apiFetch(`/api/v1/attendance/${row.id}/override`, {
      method: "POST",
      body: JSON.stringify({ status: target }),
    });
    mutate();
  };

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Attendance</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pull a class&apos;s attendance roster. Same data the bot returns when you
          ask <em>show CS201 attendance</em>.
        </p>
      </header>

      <Card className="flex flex-wrap items-end gap-3 p-4">
        <div>
          <label className="text-xs font-medium text-muted-foreground">Subject</label>
          <Input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="CS201"
            className="w-44"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">Batch</label>
          <Input
            value={batch}
            onChange={(e) => setBatch(e.target.value)}
            placeholder="(any)"
            className="w-32"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">Date</label>
          <Input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-44"
          />
        </div>
        <Button onClick={() => setSubmitted(true)} disabled={!subject}>
          Show
        </Button>
      </Card>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {error instanceof Error ? error.message : "Failed to load."}
        </Card>
      )}

      {isLoading && <Card className="p-4 text-sm text-muted-foreground">Loading…</Card>}

      {data && (
        <Card className="overflow-hidden">
          <div className="border-b border-border bg-muted/40 px-4 py-3">
            <div className="text-sm font-semibold">
              {data.subject} · {data.batch || "all batches"} · {data.class_date}
            </div>
            <div className="text-xs text-muted-foreground">
              {data.present.length} present · {data.absent.length} absent · {data.total} total
            </div>
          </div>
          {data.total === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">
              No records for that combination.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-muted/20 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="p-2 text-left">Student</th>
                  <th className="p-2 text-left">Status</th>
                  <th className="p-2 text-left">Score</th>
                  <th className="p-2 text-left">Source</th>
                  <th className="p-2"></th>
                </tr>
              </thead>
              <tbody>
                {[...data.present, ...data.absent].map((r) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="p-2 font-medium">
                      {r.full_name}
                      {r.overridden && (
                        <span className="ml-2 text-xs text-amber-600">⚙ overridden</span>
                      )}
                    </td>
                    <td className="p-2">
                      {r.status === "PRESENT" ? (
                        <span className="inline-flex items-center gap-1 text-emerald-600">
                          <CheckCircle2 className="size-4" /> Present
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-rose-600">
                          <XCircle className="size-4" /> Absent
                        </span>
                      )}
                    </td>
                    <td className="p-2 text-muted-foreground">{r.score ?? "—"}</td>
                    <td className="p-2 text-muted-foreground">{r.source ?? "—"}</td>
                    <td className="p-2 text-right">
                      <Button size="sm" variant="outline" onClick={() => onOverride(r)}>
                        Flip
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  );
}

export default function AttendancePage() {
  return (
    <RoleGuard allow={["FACULTY", "ADMIN", "SUPER_ADMIN"]}>
      <AttendanceInner />
    </RoleGuard>
  );
}
