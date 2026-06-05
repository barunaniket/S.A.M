"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";
import { CheckCircle2, XCircle } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Submission = {
  id: number;
  user_id: number;
  full_name: string;
  status: string;
  submitted_at?: string | null;
  confirmed_at?: string | null;
  file_path?: string | null;
};

type Missing = {
  user_id: number;
  full_name: string;
};

type Detail = {
  assignment: {
    id: number;
    subject: string;
    title: string;
    batch: string;
    due_at?: string | null;
    status: string;
  };
  submitted: Submission[];
  missing: Missing[];
  submitted_count: number;
  missing_count: number;
  enrolled: number;
};

function fmt(iso?: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function DetailInner() {
  const params = useParams<{ id: string }>();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;

  const { data, isLoading, error } = useSWR<Detail>(
    id ? `/api/v1/assignments/${id}/submissions` : null,
    (path: string) => apiFetch<Detail>(path),
  );

  if (isLoading) {
    return <Card className="m-8 p-4 text-sm text-muted-foreground">Loading…</Card>;
  }
  if (error) {
    return (
      <Card className="m-8 border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        {error instanceof Error ? error.message : "Load failed."}
      </Card>
    );
  }
  if (!data) return null;

  const a = data.assignment;
  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          {a.subject} — {a.title}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {a.batch} · due {fmt(a.due_at)} · {a.status}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card className="overflow-hidden">
          <div className="border-b border-border bg-muted/40 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <CheckCircle2 className="size-4 text-emerald-600" />
              Submitted ({data.submitted_count})
            </div>
          </div>
          {data.submitted.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">
              No submissions yet.
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {data.submitted.map((s) => (
                <li key={s.id} className="flex items-center justify-between p-3">
                  <div className="min-w-0">
                    <div className="font-medium">{s.full_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {s.status} · {fmt(s.submitted_at)}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="overflow-hidden">
          <div className="border-b border-border bg-muted/40 px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <XCircle className="size-4 text-rose-600" />
              Missing ({data.missing_count})
            </div>
          </div>
          {data.missing.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">
              Everyone submitted 🎉
            </div>
          ) : (
            <ul className="divide-y divide-border">
              {data.missing.map((m) => (
                <li key={m.user_id} className="p-3 text-sm">
                  {m.full_name}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

export default function AssignmentDetail() {
  return (
    <RoleGuard allow={["FACULTY", "ADMIN", "SUPER_ADMIN"]}>
      <DetailInner />
    </RoleGuard>
  );
}
