"use client";

import useSWR from "swr";
import { useState } from "react";
import { CheckCircle2, XCircle, DoorOpen } from "lucide-react";
import { RoleGuard } from "@/components/auth/RoleGuard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type Booking = {
  id: number;
  meeting_id?: string | null;
  requested_by?: number | null;
  requester_name?: string | null;
  requester_email?: string | null;
  room_label?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  purpose?: string | null;
  status: "PENDING" | "APPROVED" | "DENIED" | "CANCELLED";
  created_at: string;
};

function QueueInner() {
  const { data, mutate } = useSWR<{ bookings: Booking[] }>(
    "/api/v1/bookings/pending",
    (path: string) => apiFetch(path),
  );
  const bookings = data?.bookings ?? [];
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const decide = async (id: number, action: "approve" | "deny") => {
    setBusyId(id);
    setError(null);
    try {
      await apiFetch(`/api/v1/bookings/${id}/${action}`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      mutate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-6 overflow-y-auto p-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Booking queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Pending room/lab/hall requests waiting for your decision.
        </p>
      </header>

      {error && (
        <Card className="border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </Card>
      )}

      {bookings.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 p-10 text-center text-sm text-muted-foreground">
          <DoorOpen className="size-8" />
          <p>No pending booking requests.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {bookings.map((b) => (
            <Card key={b.id} className="p-4">
              <div className="flex items-start gap-3">
                <div className="flex-1 space-y-1">
                  <p className="font-medium">
                    {b.room_label ?? "Room TBD"}
                    <span className="ml-2 rounded bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">
                      PENDING
                    </span>
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Requested by{" "}
                    <span className="font-medium text-foreground">
                      {b.requester_name ?? "—"}
                    </span>
                    {b.requester_email ? ` (${b.requester_email})` : ""}
                  </p>
                  <p className="text-sm">
                    {b.starts_at
                      ? `${new Date(b.starts_at).toLocaleString()}${
                          b.ends_at
                            ? ` – ${new Date(b.ends_at).toLocaleTimeString()}`
                            : ""
                        }`
                      : "Time TBD"}
                  </p>
                  {b.purpose && (
                    <p className="text-sm italic text-muted-foreground">
                      “{b.purpose}”
                    </p>
                  )}
                </div>
                <div className="flex flex-col gap-2">
                  <Button
                    onClick={() => decide(b.id, "approve")}
                    disabled={busyId === b.id}
                    size="sm"
                  >
                    <CheckCircle2 className="size-4" /> Approve
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => decide(b.id, "deny")}
                    disabled={busyId === b.id}
                    size="sm"
                  >
                    <XCircle className="size-4" /> Deny
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default function BookingQueuePage() {
  return (
    <RoleGuard allow={["BOOKING_AUTHORITY"]}>
      <QueueInner />
    </RoleGuard>
  );
}
