"use client";

import Link from "next/link";
import useSWR from "swr";
import { ClipboardList, Plus } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type AdminTask = {
  id: number;
  assignee_id?: number | null;
  assignee_name?: string | null;
  assignee_email?: string | null;
  title: string;
  description?: string | null;
  deadline?: string | null;
  status: "PENDING" | "DONE" | "OVERDUE" | "CANCELLED";
  created_at: string;
};

const statusClass: Record<AdminTask["status"], string> = {
  PENDING: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  OVERDUE: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
  DONE: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  CANCELLED: "bg-muted text-muted-foreground",
};

function AdminTasksInner() {
  const { data } = useSWR<{ tasks: AdminTask[] }>(
    "/api/v1/tasks?role=admin",
    (path: string) => apiFetch(path),
  );
  const tasks = data?.tasks ?? [];

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 overflow-y-auto p-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Task assignments</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Tasks you&apos;ve assigned. Upload a new sheet/voice memo to assign more.
          </p>
        </div>
        <Link href="/app/admin/tasks/upload">
          <Button>
            <Plus className="size-4" /> New assignments
          </Button>
        </Link>
      </header>

      {tasks.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 p-10 text-center text-sm text-muted-foreground">
          <ClipboardList className="size-8" />
          <p>No tasks assigned yet.</p>
          <Link href="/app/admin/tasks/upload">
            <Button variant="outline" className="mt-2">
              Upload a task list
            </Button>
          </Link>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="p-2 text-left">Assignee</th>
                <th className="p-2 text-left">Title</th>
                <th className="p-2 text-left">Deadline</th>
                <th className="p-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id} className="border-t border-border">
                  <td className="p-2">{t.assignee_name ?? "?"}</td>
                  <td className="p-2 font-medium">{t.title}</td>
                  <td className="p-2 text-xs text-muted-foreground">
                    {t.deadline ? new Date(t.deadline).toLocaleString() : "—"}
                  </td>
                  <td className="p-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${statusClass[t.status]}`}
                    >
                      {t.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

export default function AdminTasksPage() {
  return (
    <RoleGuard allow={["ADMIN"]}>
      <AdminTasksInner />
    </RoleGuard>
  );
}
