"use client";

import Link from "next/link";
import useSWR from "swr";
import { useState } from "react";
import { Plus, Trash2, Users2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Group = {
  id: number;
  name: string;
  description: string | null;
  member_count: number;
  created_at?: string | null;
};

export default function GroupsListPage() {
  const { data, error, mutate } = useSWR<Group[]>(
    "/api/v1/groups",
    (path: string) => apiFetch(path),
  );
  const groups = data ?? [];

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      await apiFetch("/api/v1/groups", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setName("");
      setDescription("");
      mutate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    if (!confirm("Delete this group? Members will be removed from it but their accounts stay.")) return;
    try {
      await apiFetch(`/api/v1/groups/${id}`, { method: "DELETE" });
      mutate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    }
  };

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Groups</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Cohorts, classes, and broadcast targets. SAM uses these for class
          cancellations and meeting participant resolution
          (e.g. <code>cs faculty</code>, <code>CSE-3A</code>).
        </p>
      </header>

      {(err || error) && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {err ?? (error as Error)?.message}
        </Card>
      )}

      {/* Create */}
      <Card className="space-y-3 p-4">
        <h2 className="text-sm font-medium">Create a new group</h2>
        <div className="grid gap-2 md:grid-cols-[1fr_2fr_auto]">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. CSE-3A, cs faculty)"
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="rounded-md border bg-background px-3 py-2 text-sm"
          />
          <Button onClick={create} disabled={busy || !name.trim()}>
            <Plus className="size-4" /> Create
          </Button>
        </div>
      </Card>

      {/* List */}
      {groups.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 p-10 text-center text-sm text-muted-foreground">
          <Users2 className="size-8" />
          No groups yet. Create one above to get started.
        </Card>
      ) : (
        <Card className="divide-y divide-border">
          {groups.map((g) => (
            <div key={g.id} className="flex items-center gap-3 p-3 text-sm">
              <Link
                href={`/app/super-admin/groups/${g.id}`}
                className="min-w-0 flex-1 hover:underline"
              >
                <div className="font-medium">{g.name}</div>
                {g.description && (
                  <div className="text-xs text-muted-foreground">
                    {g.description}
                  </div>
                )}
              </Link>
              <span className="text-xs text-muted-foreground">
                {g.member_count} member{g.member_count === 1 ? "" : "s"}
              </span>
              <button
                onClick={() => remove(g.id)}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                title="Delete group"
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
