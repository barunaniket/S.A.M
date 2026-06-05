"use client";

import Link from "next/link";
import useSWR from "swr";
import { ArrowRight, ClipboardList } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Assignment = {
  id: number;
  subject: string;
  title: string;
  batch: string;
  status: "OPEN" | "CLOSED" | "ARCHIVED";
  due_at?: string | null;
  submitted: number;
  enrolled: number;
};

function fmt(iso?: string | null): string {
  if (!iso) return "no deadline";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function AssignmentsInner() {
  const { data, isLoading, error } = useSWR<Assignment[]>(
    "/api/v1/assignments/mine",
    (path: string) => apiFetch<Assignment[]>(path),
  );

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">My assignments</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Open + recently-closed work you&apos;ve published. Click in to see who&apos;s submitted.
        </p>
      </header>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {error instanceof Error ? error.message : "Load failed."}
        </Card>
      )}
      {isLoading && (
        <Card className="p-4 text-sm text-muted-foreground">Loading…</Card>
      )}

      {data && data.length === 0 && (
        <Card className="p-6 text-sm text-muted-foreground">
          No assignments yet. From the chat or Telegram, say <em>create assignment for &lt;batch&gt;</em>.
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="space-y-3">
          {data.map((a) => {
            const ratio = a.enrolled > 0 ? a.submitted / a.enrolled : 0;
            const pct = Math.round(ratio * 100);
            return (
              <Link
                key={a.id}
                href={`/app/faculty/assignments/${a.id}`}
                className="block"
              >
                <Card className="flex items-center gap-4 p-4 transition-colors hover:bg-muted/30">
                  <ClipboardList className="size-5 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                      <span className="font-medium">
                        {a.subject} — {a.title}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {a.batch} · {a.status}
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Due {fmt(a.due_at)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-medium">
                      {a.submitted}/{a.enrolled}
                    </div>
                    <div className="text-xs text-muted-foreground">{pct}% in</div>
                  </div>
                  <ArrowRight className="size-4 text-muted-foreground" />
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function AssignmentsPage() {
  return (
    <RoleGuard allow={["FACULTY", "ADMIN", "SUPER_ADMIN"]}>
      <AssignmentsInner />
    </RoleGuard>
  );
}
