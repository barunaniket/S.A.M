"use client";

import useSWR from "swr";
import { useMemo, useState } from "react";
import { FileSearch, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type UnionRow = {
  source: "conversation" | "whatsapp";
  id: number;
  channel: string | null;
  role_or_direction: string | null;
  msg_type: string | null;
  body: string | null;
  intent: string | null;
  created_at: string | null;
  user_id: number | null;
  user_name: string | null;
  user_email: string | null;
  phone: string | null;
};

type AuditUser = {
  id: number;
  full_name: string | null;
  email: string | null;
};

const CHANNELS = ["", "telegram", "whatsapp", "system"];
const PRESET_LIMITS = [25, 50, 100, 200];

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function snippet(s: string | null, n: number = 160): string {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export default function AuditLogPage() {
  const [tab, setTab] = useState<"all" | "conversations" | "whatsapp">("all");
  const [channel, setChannel] = useState<string>("");
  const [userId, setUserId] = useState<string>("");
  const [since, setSince] = useState<string>("");
  const [q, setQ] = useState<string>("");
  const [limit, setLimit] = useState<number>(50);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  // user dropdown source
  const { data: usersWrap } = useSWR<{ users: AuditUser[] }>(
    "/api/v1/admin/users",
    (path: string) => apiFetch(path),
  );
  const users = usersWrap?.users ?? [];

  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (channel) params.set("channel", channel);
    if (userId) params.set("user_id", userId);
    if (since) {
      // <input type="datetime-local"> gives "YYYY-MM-DDTHH:MM" — fine for FastAPI.
      params.set("since", since);
    }
    if (q) params.set("q", q);
    params.set("limit", String(limit));
    const base =
      tab === "conversations"
        ? "/api/v1/admin/audit/conversations"
        : tab === "whatsapp"
        ? "/api/v1/admin/audit/whatsapp"
        : "/api/v1/admin/audit";
    return `${base}?${params.toString()}`;
  }, [tab, channel, userId, since, q, limit]);

  const { data, error, isLoading, mutate } = useSWR<UnionRow[]>(
    path,
    (p: string) => apiFetch(p),
    { refreshInterval: 15000 },
  );

  const rows = data ?? [];

  const tabs: { key: typeof tab; label: string }[] = [
    { key: "all",           label: "All" },
    { key: "conversations", label: "Conversations" },
    { key: "whatsapp",      label: "WhatsApp" },
  ];

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-8">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <FileSearch className="size-6" /> Audit log
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Conversation log + WhatsApp audit. Refreshes every 15 s.
        </p>
      </header>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={
              "border-b-2 px-3 py-2 text-sm font-medium transition-colors " +
              (tab === t.key
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground")
            }
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => mutate()}>
            <RotateCw className="size-3.5" /> Refresh
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card className="grid gap-2 p-3 md:grid-cols-[160px_1fr_180px_140px_120px]">
        <select
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          className="rounded-md border bg-background px-2 py-1.5 text-sm"
          disabled={tab === "whatsapp"}
        >
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {c ? c : "All channels"}
            </option>
          ))}
        </select>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search content/body…"
          className="rounded-md border bg-background px-2 py-1.5 text-sm"
        />
        <select
          value={userId}
          onChange={(e) => setUserId(e.target.value)}
          className="rounded-md border bg-background px-2 py-1.5 text-sm"
        >
          <option value="">All users</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name || u.email || `#${u.id}`}
            </option>
          ))}
        </select>
        <input
          type="datetime-local"
          value={since}
          onChange={(e) => setSince(e.target.value)}
          className="rounded-md border bg-background px-2 py-1.5 text-sm"
        />
        <select
          value={limit}
          onChange={(e) => setLimit(Number(e.target.value))}
          className="rounded-md border bg-background px-2 py-1.5 text-sm"
        >
          {PRESET_LIMITS.map((n) => (
            <option key={n} value={n}>
              {n} rows
            </option>
          ))}
        </select>
      </Card>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {(error as Error).message}
        </Card>
      )}

      {/* Rows */}
      <Card className="overflow-hidden">
        {isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No log entries match these filters.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="p-2 text-left">Time</th>
                <th className="p-2 text-left">Source</th>
                <th className="p-2 text-left">Channel</th>
                <th className="p-2 text-left">Role/Dir</th>
                <th className="p-2 text-left">Type</th>
                <th className="p-2 text-left">User</th>
                <th className="p-2 text-left">Content</th>
                <th className="p-2 text-left">Intent</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const key = `${r.source}-${r.id}`;
                const isOpen = expanded[key];
                return (
                  <tr key={key} className="border-t border-border align-top">
                    <td className="p-2 text-xs text-muted-foreground whitespace-nowrap">
                      {fmtTime(r.created_at)}
                    </td>
                    <td className="p-2 text-xs">
                      <span
                        className={
                          "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase " +
                          (r.source === "whatsapp"
                            ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                            : "bg-sky-500/15 text-sky-700 dark:text-sky-300")
                        }
                      >
                        {r.source}
                      </span>
                    </td>
                    <td className="p-2 text-xs">{r.channel ?? "—"}</td>
                    <td className="p-2 text-xs">{r.role_or_direction ?? "—"}</td>
                    <td className="p-2 text-xs">{r.msg_type ?? "—"}</td>
                    <td className="p-2 text-xs">
                      <div className="font-medium">{r.user_name ?? "—"}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {r.user_email ?? r.phone ?? ""}
                      </div>
                    </td>
                    <td className="p-2 max-w-md text-xs">
                      <button
                        onClick={() =>
                          setExpanded((p) => ({ ...p, [key]: !p[key] }))
                        }
                        className="text-left hover:underline"
                      >
                        {isOpen ? r.body : snippet(r.body)}
                      </button>
                    </td>
                    <td className="p-2 text-xs text-muted-foreground">
                      {r.intent ?? "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
