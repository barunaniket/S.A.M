"use client";

import { CalendarDays, ExternalLink } from "lucide-react";
import { useAgenda } from "@/hooks/useAgenda";
import { Skeleton } from "@/components/ui/skeleton";

function formatTime(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatToday() {
  return new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

export function AgendaStrip() {
  const { data, isLoading, error } = useAgenda();

  return (
    <div className="border-b border-border bg-muted/30 px-6 py-4">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <CalendarDays className="size-3.5" />
        Today &middot; {formatToday()}
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      )}

      {error && (
        <p className="text-sm text-muted-foreground">
          Couldn&apos;t load today&apos;s agenda.
        </p>
      )}

      {!isLoading && !error && (!data?.meetings || data.meetings.length === 0) && (
        <p className="text-sm text-muted-foreground">
          Nothing on the calendar today.
        </p>
      )}

      {!isLoading && !error && data?.meetings && data.meetings.length > 0 && (
        <ul className="space-y-1.5">
          {data.meetings.slice(0, 4).map((m, i) => (
            <li
              key={m.id ?? i}
              className="flex items-center gap-3 text-sm"
            >
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {formatTime(m.start)}
              </span>
              <span className="font-medium">{m.title ?? "Untitled"}</span>
              {Array.isArray(m.attendees) && m.attendees.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  · {m.attendees.length}
                </span>
              )}
              {m.meet_link && (
                <a
                  href={m.meet_link}
                  target="_blank"
                  rel="noreferrer"
                  className="text-muted-foreground hover:text-foreground"
                  aria-label="Open Meet link"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              )}
            </li>
          ))}
          {data.meetings.length > 4 && (
            <li className="text-xs text-muted-foreground">
              + {data.meetings.length - 4} more
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
