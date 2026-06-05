"use client";

import Link from "next/link";
import useSWR from "swr";
import { useState } from "react";
import { ArrowLeft, Trash2, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Member = {
  id: number;
  email: string | null;
  name?: string | null;       // group_service.list_members returns full_name as 'name'
  full_name?: string | null;
  phone?: string | null;
  phone_number?: string | null;
  role: string | null;
  department: string | null;
};

type Group = {
  id: number;
  name: string;
  description?: string | null;
  member_count: number;
};

export default function GroupDetailPage({
  params,
}: {
  params: { groupId: string };
}) {
  const gid = Number(params.groupId);

  const { data: groupsList } = useSWR<Group[]>(
    "/api/v1/groups",
    (path: string) => apiFetch<Group[]>(path),
  );
  const group = groupsList?.find((g) => g.id === gid);

  const { data: members, mutate } = useSWR<Member[]>(
    Number.isFinite(gid) ? `/api/v1/groups/${gid}/members` : null,
    (path: string) => apiFetch<Member[]>(path),
  );
  const memberRows = members ?? [];

  const [emailsRaw, setEmailsRaw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<{ added: number; missing: string[] } | null>(null);

  const add = async () => {
    const emails = emailsRaw
      .split(/[\s,;]+/)
      .map((e) => e.trim())
      .filter((e) => e.includes("@"));
    if (!emails.length) {
      setErr("Enter at least one valid email address.");
      return;
    }
    setBusy(true);
    setErr(null);
    setLastResult(null);
    try {
      const res = await apiFetch<{ added: number; missing_emails: string[] }>(
        `/api/v1/groups/${gid}/members`,
        {
          method: "POST",
          body: JSON.stringify({ emails }),
        },
      );
      setEmailsRaw("");
      setLastResult({ added: res.added, missing: res.missing_emails ?? [] });
      mutate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Add failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (uid: number) => {
    if (!confirm("Remove this member from the group?")) return;
    try {
      await apiFetch(`/api/v1/groups/${gid}/members/${uid}`, { method: "DELETE" });
      mutate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Remove failed");
    }
  };

  if (!Number.isFinite(gid)) {
    return <div className="p-8 text-sm text-destructive">Bad URL</div>;
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-8">
      <header className="flex items-center gap-3">
        <Link
          href="/app/super-admin/groups"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="inline size-4" /> Back to groups
        </Link>
      </header>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {group?.name ?? `Group #${gid}`}
        </h1>
        {group?.description && (
          <p className="mt-1 text-sm text-muted-foreground">{group.description}</p>
        )}
        <p className="mt-1 text-xs text-muted-foreground">
          {memberRows.length} member{memberRows.length === 1 ? "" : "s"}
        </p>
      </div>

      {(err) && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {err}
        </Card>
      )}

      {/* Add by email */}
      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-medium">Add members by email</h2>
        <textarea
          value={emailsRaw}
          onChange={(e) => setEmailsRaw(e.target.value)}
          rows={3}
          placeholder="alice@uni.edu, bob@uni.edu&#10;…or one per line"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <div className="flex items-center gap-2">
          <Button onClick={add} disabled={busy || !emailsRaw.trim()}>
            <UserPlus className="size-4" />
            {busy ? "Adding…" : "Add"}
          </Button>
          {lastResult && (
            <span className="text-xs text-muted-foreground">
              Added {lastResult.added}.
              {lastResult.missing.length
                ? ` Not found: ${lastResult.missing.join(", ")}`
                : ""}
            </span>
          )}
        </div>
      </Card>

      {/* Members table */}
      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="p-3 text-left">Name</th>
              <th className="p-3 text-left">Email</th>
              <th className="p-3 text-left">Role</th>
              <th className="p-3 text-left">Department</th>
              <th className="p-3 text-left">Phone</th>
              <th className="p-3"></th>
            </tr>
          </thead>
          <tbody>
            {memberRows.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-6 text-center text-muted-foreground">
                  No members yet.
                </td>
              </tr>
            ) : (
              memberRows.map((m) => (
                <tr key={m.id} className="border-t border-border">
                  <td className="p-3">{m.full_name ?? m.name ?? "—"}</td>
                  <td className="p-3 text-muted-foreground">{m.email ?? "—"}</td>
                  <td className="p-3 text-xs">{m.role ?? "—"}</td>
                  <td className="p-3 text-xs">{m.department ?? "—"}</td>
                  <td className="p-3 text-xs">{m.phone_number ?? m.phone ?? "—"}</td>
                  <td className="p-3 text-right">
                    <button
                      onClick={() => remove(m.id)}
                      className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                      title="Remove from group"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
