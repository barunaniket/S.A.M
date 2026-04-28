"use client";

import { useEffect, useState } from "react";
import { LogOut, RefreshCw, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ConnectGoogleButton } from "@/components/auth/ConnectGoogleButton";
import { useAuth } from "@/hooks/useAuth";
import { useGoogleStatus } from "@/hooks/useGoogleStatus";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

const tabs = [
  { id: "account", label: "Account" },
  { id: "briefing", label: "Daily briefing" },
  { id: "google", label: "Google Calendar" },
  { id: "about", label: "About" },
] as const;

type TabId = (typeof tabs)[number]["id"];

type Prefs = {
  briefing_time: string;
  timezone: string;
  briefing_enabled: boolean;
};

export default function SettingsPage() {
  const [tab, setTab] = useState<TabId>("account");
  const { user, logout } = useAuth();
  const { data: status, mutate, isLoading } = useGoogleStatus();

  return (
    <div className="h-full overflow-y-auto px-6 py-8">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your S.A.M account and the connected Google Calendar.
        </p>

        <div className="mt-6 flex gap-1 border-b border-border">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                tab === t.id
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {tab === "account" && (
            <Card>
              <CardHeader>
                <CardTitle>Account</CardTitle>
                <CardDescription>
                  You&apos;re the sole authenticated user — the SPOC. Faculty
                  receive invites but never log in.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <Field label="Name" value={user?.name ?? "—"} />
                <Field label="Email" value={user?.email ?? "—"} />
                <Field label="Role" value={user?.role ?? "FACULTY"} />
                <Separator />
                <Button variant="destructive" onClick={logout} className="gap-2">
                  <LogOut className="size-4" /> Sign out
                </Button>
              </CardContent>
            </Card>
          )}

          {tab === "briefing" && <BriefingPanel />}

          {tab === "google" && (
            <Card>
              <CardHeader>
                <CardTitle>Google Calendar</CardTitle>
                <CardDescription>
                  S.A.M uses your Google account to read freebusy data and
                  write meeting events.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center justify-between rounded-lg border border-border p-4">
                  <div>
                    <p className="text-sm font-medium">Connection status</p>
                    <p className="text-xs text-muted-foreground">
                      {isLoading ? "Checking…" : statusMessage(status)}
                    </p>
                  </div>
                  <StatusBadge data={status} loading={isLoading} />
                </div>

                <div className="flex flex-wrap gap-2">
                  <ConnectGoogleButton
                    label={
                      status?.connected ? "Reconnect Google" : "Connect Google Calendar"
                    }
                    variant={status?.connected ? "outline" : "default"}
                  />
                  <Button
                    variant="ghost"
                    onClick={() => mutate()}
                    className="gap-2"
                  >
                    <RefreshCw className="size-4" /> Refresh
                  </Button>
                  <Button variant="ghost" disabled title="Coming soon">
                    Disconnect
                  </Button>
                </div>

                <p className="text-xs text-muted-foreground">
                  Refresh tokens are encrypted with Fernet before storage. You
                  can rotate the encryption key — see the operational notes in
                  the README.
                </p>
              </CardContent>
            </Card>
          )}

          {tab === "about" && (
            <Card>
              <CardHeader>
                <CardTitle>About</CardTitle>
                <CardDescription>Build and runtime information.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 text-sm">
                <Field label="Frontend" value="Next.js 14 + Tailwind" />
                <Field
                  label="API base"
                  value={process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"}
                />
                <Field label="Backend" value="FastAPI · S.A.M v2.0" />
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function BriefingPanel() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch<{ preferences: Prefs }>("/api/v1/me/preferences")
      .then((d) => setPrefs(d.preferences))
      .catch((e: Error) => setError(e.message));
  }, []);

  const save = async () => {
    if (!prefs) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await apiFetch("/api/v1/me/preferences", {
        method: "PUT",
        body: JSON.stringify(prefs),
      });
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  if (!prefs) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          {error ?? "Loading…"}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Daily briefing</CardTitle>
        <CardDescription>
          S.A.M. sends you a morning summary on WhatsApp — today&apos;s
          classes, meetings, tasks due, and any academic events.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <label className="flex items-center gap-3 text-sm">
          <input
            type="checkbox"
            checked={prefs.briefing_enabled}
            onChange={(e) =>
              setPrefs({ ...prefs, briefing_enabled: e.target.checked })
            }
          />
          Send me a daily briefing
        </label>

        <div className="grid grid-cols-[140px_1fr] items-center gap-3 text-sm">
          <span className="text-muted-foreground">Briefing time</span>
          <input
            type="time"
            value={prefs.briefing_time}
            onChange={(e) =>
              setPrefs({ ...prefs, briefing_time: e.target.value })
            }
            className="w-32 rounded border bg-background px-2 py-1"
          />
        </div>
        <div className="grid grid-cols-[140px_1fr] items-center gap-3 text-sm">
          <span className="text-muted-foreground">Timezone</span>
          <input
            value={prefs.timezone}
            onChange={(e) => setPrefs({ ...prefs, timezone: e.target.value })}
            placeholder="Asia/Kolkata"
            className="w-60 rounded border bg-background px-2 py-1"
          />
        </div>

        {error && (
          <p className="text-sm text-destructive">{error}</p>
        )}
        {saved && (
          <p className="text-sm text-emerald-600">Saved.</p>
        )}

        <Button onClick={save} disabled={busy} className="gap-2">
          <Save className="size-4" /> {busy ? "Saving…" : "Save"}
        </Button>
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[140px_1fr] items-center gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}

function StatusBadge({
  data,
  loading,
}: {
  data: { connected: boolean; reason?: string } | undefined;
  loading: boolean;
}) {
  if (loading || !data) return <Badge variant="outline">Checking…</Badge>;
  if (data.connected) return <Badge variant="success">Connected</Badge>;
  if (data.reason === "expired") return <Badge variant="warning">Expired</Badge>;
  return <Badge variant="destructive">Not connected</Badge>;
}

function statusMessage(s: { connected: boolean; reason?: string } | undefined) {
  if (!s) return "Unable to reach the backend.";
  if (s.connected) return "Calendar reads and writes are working.";
  if (s.reason === "expired") return "Your token expired or was revoked. Reconnect below.";
  return "No Google account connected yet.";
}
