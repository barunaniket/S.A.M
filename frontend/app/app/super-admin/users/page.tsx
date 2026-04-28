"use client";

import { useState } from "react";
import useSWR from "swr";
import { Save } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type User = {
  id: number;
  email: string;
  full_name?: string | null;
  role?: string | null;
  department?: string | null;
  phone_number?: string | null;
  is_onboarded?: boolean;
  created_at?: string;
};

const ROLES = [
  "ADMIN",
  "FACULTY",
  "STUDENT",
  "BOOKING_AUTHORITY",
  "SUPER_ADMIN",
];

function UsersInner() {
  const { data, mutate } = useSWR<{ users: User[] }>(
    "/api/v1/admin/users",
    (path: string) => apiFetch(path),
  );
  const users = data?.users ?? [];

  const [filter, setFilter] = useState("");
  const [edits, setEdits] = useState<Record<number, Partial<User>>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const filtered = users.filter((u) => {
    if (!filter) return true;
    const f = filter.toLowerCase();
    return (
      (u.full_name ?? "").toLowerCase().includes(f) ||
      u.email.toLowerCase().includes(f) ||
      (u.department ?? "").toLowerCase().includes(f) ||
      (u.role ?? "").toLowerCase().includes(f)
    );
  });

  const setEdit = (id: number, patch: Partial<User>) =>
    setEdits((p) => ({ ...p, [id]: { ...(p[id] ?? {}), ...patch } }));

  const save = async (id: number) => {
    if (!edits[id]) return;
    setBusy(id);
    setError(null);
    try {
      await apiFetch(`/api/v1/admin/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(edits[id]),
      });
      setEdits((p) => {
        const next = { ...p };
        delete next[id];
        return next;
      });
      mutate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col gap-6 overflow-y-auto p-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">User management</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Update roles, phone numbers, and departments. {users.length} user(s).
          </p>
        </div>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search by name / email / role"
          className="w-72 rounded-md border bg-background px-3 py-1.5 text-sm"
        />
      </header>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </Card>
      )}

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="p-2 text-left">Name / email</th>
              <th className="p-2 text-left">Role</th>
              <th className="p-2 text-left">Department</th>
              <th className="p-2 text-left">Phone</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => {
              const dirty = !!edits[u.id];
              const merged = { ...u, ...(edits[u.id] ?? {}) };
              return (
                <tr key={u.id} className="border-t border-border">
                  <td className="p-2">
                    <div className="font-medium">{merged.full_name ?? "—"}</div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </td>
                  <td className="p-2">
                    <select
                      value={merged.role ?? ""}
                      onChange={(e) => setEdit(u.id, { role: e.target.value })}
                      className="rounded border bg-background px-2 py-1"
                    >
                      <option value="">—</option>
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="p-2">
                    <input
                      value={merged.department ?? ""}
                      onChange={(e) => setEdit(u.id, { department: e.target.value })}
                      className="w-40 rounded border bg-background px-2 py-1"
                    />
                  </td>
                  <td className="p-2">
                    <input
                      value={merged.phone_number ?? ""}
                      onChange={(e) =>
                        setEdit(u.id, { phone_number: e.target.value })
                      }
                      placeholder="+91…"
                      className="w-44 rounded border bg-background px-2 py-1"
                    />
                  </td>
                  <td className="p-2 text-right">
                    <Button
                      size="sm"
                      onClick={() => save(u.id)}
                      disabled={!dirty || busy === u.id}
                    >
                      <Save className="size-4" />
                      {busy === u.id ? "Saving…" : "Save"}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

export default function UsersPage() {
  return (
    <RoleGuard allow={["SUPER_ADMIN"]}>
      <UsersInner />
    </RoleGuard>
  );
}
