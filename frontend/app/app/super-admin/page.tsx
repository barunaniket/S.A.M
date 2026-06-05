"use client";

import useSWR from "swr";
import {
  Activity,
  Briefcase,
  CalendarDays,
  CheckCircle2,
  Clock,
  DoorOpen,
  GraduationCap,
  Users,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type RecentRow = {
  channel: string | null;
  role: string | null;
  content: string | null;
  intent: string | null;
  user_id: number | null;
  user_name: string | null;
  created_at: string | null;
};

type DashboardData = {
  users: Record<string, number>;
  groups: number;
  today: { meetings: number; tasks_due: number; classes: number };
  pending_bookings: number;
  academic_events_30d: number;
  recent: RecentRow[];
};

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

function Metric({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string;
  value: number | string;
  icon: typeof Users;
  hint?: string;
}) {
  return (
    <Card className="flex items-center gap-4 p-4">
      <div className="grid size-10 place-items-center rounded-md bg-primary/10 text-primary">
        <Icon className="size-5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div className="text-2xl font-semibold leading-tight">{value}</div>
        {hint && (
          <div className="text-xs text-muted-foreground">{hint}</div>
        )}
      </div>
    </Card>
  );
}

export default function SuperAdminOverviewPage() {
  const { data, error, isLoading } = useSWR<DashboardData>(
    "/api/v1/admin/dashboard",
    (path: string) => apiFetch(path),
    { refreshInterval: 30000 },
  );

  if (isLoading) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Loading…</div>
    );
  }
  if (error || !data) {
    return (
      <div className="p-8 text-sm text-destructive">
        Couldn&apos;t load the dashboard: {(error as Error)?.message ?? "no data"}
      </div>
    );
  }

  const totalUsers = Object.values(data.users).reduce((a, b) => a + b, 0);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Org-wide snapshot. Refreshes every 30 seconds.
        </p>
      </header>

      {/* Snapshot row */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          label="Total users"
          value={totalUsers}
          icon={Users}
          hint={`${data.users.FACULTY ?? 0} faculty · ${data.users.STUDENT ?? 0} students`}
        />
        <Metric label="Groups"           value={data.groups}              icon={GraduationCap} />
        <Metric label="Pending bookings" value={data.pending_bookings}    icon={DoorOpen} />
        <Metric label="Events (30d)"     value={data.academic_events_30d} icon={CalendarDays} />
      </section>

      {/* Today */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Today
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <Metric label="Classes scheduled" value={data.today.classes}   icon={Clock} />
          <Metric label="Meetings"          value={data.today.meetings}  icon={Briefcase} />
          <Metric label="Tasks due"         value={data.today.tasks_due} icon={CheckCircle2} />
        </div>
      </section>

      {/* Users by role */}
      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Users by role
        </h2>
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="p-3 text-left">Role</th>
                <th className="p-3 text-right">Count</th>
              </tr>
            </thead>
            <tbody>
              {(["SUPER_ADMIN", "ADMIN", "FACULTY", "BOOKING_AUTHORITY", "STUDENT"] as const).map((r) => (
                <tr key={r} className="border-t border-border">
                  <td className="p-3">{r}</td>
                  <td className="p-3 text-right font-medium">{data.users[r] ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>

      {/* Recent activity */}
      <section>
        <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          <Activity className="size-4" /> Recent activity
        </h2>
        {data.recent.length === 0 ? (
          <Card className="p-6 text-sm text-muted-foreground">
            No conversation log entries yet.
          </Card>
        ) : (
          <Card className="divide-y divide-border">
            {data.recent.map((r, i) => (
              <div key={i} className="flex items-start gap-3 p-3 text-sm">
                <span className="mt-0.5 inline-flex w-20 shrink-0 items-center rounded bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  {r.channel ?? "—"}
                </span>
                <span className="mt-0.5 inline-flex w-20 shrink-0 items-center text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                  {r.role ?? ""}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate">{r.content}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {r.user_name ?? "—"}
                    {r.intent ? ` · ${r.intent}` : ""}
                    {" · "}
                    {relativeTime(r.created_at)}
                  </div>
                </div>
              </div>
            ))}
          </Card>
        )}
      </section>
    </div>
  );
}
