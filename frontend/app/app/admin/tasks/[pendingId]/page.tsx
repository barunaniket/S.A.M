"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type PendingTask = {
  assignee_name: string;
  title: string;
  description?: string | null;
  deadline?: string | null;
};

function ReviewInner({ pendingId }: { pendingId: number }) {
  const router = useRouter();
  const [tasks, setTasks] = useState<PendingTask[]>([]);
  const [needsReview, setNeedsReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    apiFetch<{ tasks: PendingTask[]; needs_review: boolean }>(
      `/api/v1/tasks/pending/${pendingId}`,
    )
      .then((res) => {
        setTasks(res.tasks ?? []);
        setNeedsReview(res.needs_review);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoaded(true));
  }, [pendingId]);

  const update = (idx: number, patch: Partial<PendingTask>) =>
    setTasks((p) => p.map((t, i) => (i === idx ? { ...t, ...patch } : t)));
  const remove = (idx: number) =>
    setTasks((p) => p.filter((_, i) => i !== idx));
  const addRow = () =>
    setTasks((p) => [
      ...p,
      { assignee_name: "", title: "", description: null, deadline: null },
    ]);

  const onConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await apiFetch<{
        created: number;
        notified: number;
        unmatched: number;
      }>(`/api/v1/tasks/confirm/${pendingId}`, {
        method: "POST",
        body: JSON.stringify({
          tasks: tasks.map((t) => ({
            ...t,
            deadline: t.deadline || null,
          })),
        }),
      });
      router.push(`/app/admin/tasks?notified=${res.notified}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) {
    return (
      <p className="p-8 text-sm text-muted-foreground">Loading…</p>
    );
  }

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          Review task assignments
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Edit the parsed list. On confirm, each assignee gets a personalised
          DM and 24h/4h/1h reminders are scheduled.
        </p>
      </header>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </Card>
      )}
      {needsReview && (
        <Card className="border-amber-500/40 bg-amber-500/5 p-3 text-xs">
          Some entries looked ambiguous — please review carefully.
        </Card>
      )}

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="p-2 text-left">Assignee</th>
              <th className="p-2 text-left">Title</th>
              <th className="p-2 text-left">Deadline</th>
              <th className="p-2 text-left">Description</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t, i) => (
              <tr key={i} className="border-t border-border">
                <td className="p-2">
                  <input
                    value={t.assignee_name}
                    onChange={(e) => update(i, { assignee_name: e.target.value })}
                    className="w-full rounded border bg-background px-2 py-1"
                  />
                </td>
                <td className="p-2">
                  <input
                    value={t.title}
                    onChange={(e) => update(i, { title: e.target.value })}
                    className="w-full rounded border bg-background px-2 py-1"
                  />
                </td>
                <td className="p-2">
                  <input
                    type="datetime-local"
                    value={t.deadline ? t.deadline.slice(0, 16) : ""}
                    onChange={(e) =>
                      update(i, { deadline: e.target.value || null })
                    }
                    className="rounded border bg-background px-2 py-1"
                  />
                </td>
                <td className="p-2">
                  <input
                    value={t.description ?? ""}
                    onChange={(e) =>
                      update(i, { description: e.target.value || null })
                    }
                    className="w-full rounded border bg-background px-2 py-1"
                  />
                </td>
                <td className="p-2 text-right">
                  <button
                    onClick={() => remove(i)}
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
        <Button variant="outline" onClick={addRow} disabled={busy}>
          Add row
        </Button>
        <Button onClick={onConfirm} disabled={busy || tasks.length === 0}>
          {busy ? "Sending…" : `Send out ${tasks.length} task(s)`}
        </Button>
        <Button
          variant="ghost"
          onClick={() => router.push("/app/admin/tasks")}
          disabled={busy}
        >
          Cancel
        </Button>
      </div>
    </div>
  );
}

export default function TaskReviewPage({
  params,
}: {
  params: { pendingId: string };
}) {
  const pid = Number(params.pendingId);
  if (!Number.isFinite(pid)) {
    return <p className="p-8 text-sm text-destructive">Bad URL</p>;
  }
  return (
    <RoleGuard allow={["ADMIN"]}>
      <ReviewInner pendingId={pid} />
    </RoleGuard>
  );
}
