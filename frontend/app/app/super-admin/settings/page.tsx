"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Save } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";

type SettingsBlob = Record<string, unknown>;

const FIELDS: Array<{
  key: string;
  label: string;
  description: string;
  kind: "bool" | "int" | "intlist";
}> = [
  {
    key: "mcq_attendance_enabled",
    label: "Enable MCQ attendance",
    description: "When off, the MCQ flow is hidden in chat and the bank is bypassed.",
    kind: "bool",
  },
  {
    key: "mcq_threshold",
    label: "MCQ pass threshold",
    description: "Minimum correct answers (out of 5) for PRESENT.",
    kind: "int",
  },
  {
    key: "mcq_window_seconds",
    label: "MCQ seconds per question",
    description: "How long each rapid-fire question stays open.",
    kind: "int",
  },
  {
    key: "poll_window_seconds",
    label: "Quick Poll window (seconds)",
    description: "Default duration for the I'm-here poll before auto-close.",
    kind: "int",
  },
  {
    key: "assignment_nudge_hours",
    label: "Deadline nudge offsets (hours)",
    description: "Hours before due_at to ping non-submitters. Comma-separated, e.g. 24,1.",
    kind: "intlist",
  },
];

function SettingsInner() {
  const { data, mutate } = useSWR<SettingsBlob>(
    "/api/v1/settings",
    (path: string) => apiFetch<SettingsBlob>(path),
  );
  const [draft, setDraft] = useState<SettingsBlob>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data) setDraft({ ...data });
  }, [data]);

  const setField = (k: string, v: unknown) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [k]: v }));
  };

  const onSave = async () => {
    setBusy(true);
    setError(null);
    try {
      // coerce intlist string to number[]
      const payload: Record<string, unknown> = {};
      for (const f of FIELDS) {
        const v = draft[f.key];
        if (f.kind === "intlist") {
          if (typeof v === "string") {
            payload[f.key] = v
              .split(",")
              .map((s) => Number.parseFloat(s.trim()))
              .filter((n) => Number.isFinite(n));
          } else {
            payload[f.key] = v;
          }
        } else if (f.kind === "int") {
          payload[f.key] = Number.parseInt(String(v), 10);
        } else if (f.kind === "bool") {
          payload[f.key] = !!v;
        }
      }
      await apiFetch(`/api/v1/settings`, {
        method: "PATCH",
        body: JSON.stringify({ settings: payload }),
      });
      setSaved(true);
      mutate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Org settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Toggles and thresholds applied across the whole org. Changes take effect immediately.
        </p>
      </header>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </Card>
      )}
      {saved && (
        <Card className="border-emerald-500/40 bg-emerald-500/5 p-3 text-sm text-emerald-700">
          Saved.
        </Card>
      )}

      <Card className="space-y-4 p-4">
        {FIELDS.map((f) => {
          const v = draft[f.key];
          return (
            <div key={f.key} className="border-b border-border pb-4 last:border-b-0 last:pb-0">
              <div className="mb-2">
                <div className="text-sm font-medium">{f.label}</div>
                <div className="text-xs text-muted-foreground">{f.description}</div>
              </div>
              {f.kind === "bool" ? (
                <label className="inline-flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={!!v}
                    onChange={(e) => setField(f.key, e.target.checked)}
                  />
                  {v ? "Enabled" : "Disabled"}
                </label>
              ) : f.kind === "int" ? (
                <Input
                  type="number"
                  className="w-32"
                  value={String(v ?? "")}
                  onChange={(e) => setField(f.key, e.target.value)}
                />
              ) : (
                <Input
                  className="w-64"
                  value={Array.isArray(v) ? (v as number[]).join(",") : String(v ?? "")}
                  onChange={(e) => setField(f.key, e.target.value)}
                />
              )}
            </div>
          );
        })}
        <Button onClick={onSave} disabled={busy}>
          <Save className="size-4" />
          {busy ? "Saving…" : "Save"}
        </Button>
      </Card>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <RoleGuard allow={["SUPER_ADMIN"]}>
      <SettingsInner />
    </RoleGuard>
  );
}
