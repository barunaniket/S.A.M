"use client";

import Link from "next/link";
import { useGoogleStatus } from "@/hooks/useGoogleStatus";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function OAuthStatusPill() {
  const { data, isLoading, error } = useGoogleStatus();

  if (isLoading || (!data && !error)) {
    return (
      <Badge variant="outline" className="gap-1.5">
        <Dot className="bg-muted-foreground" />
        Checking…
      </Badge>
    );
  }

  if (error || !data) {
    return (
      <Link href="/app/settings">
        <Badge variant="destructive" className="cursor-pointer gap-1.5">
          <Dot className="bg-destructive" />
          Status unavailable
        </Badge>
      </Link>
    );
  }

  if (data.connected) {
    return (
      <Link href="/app/settings">
        <Badge variant="success" className="cursor-pointer gap-1.5">
          <Dot className="bg-emerald-500" />
          Google connected
        </Badge>
      </Link>
    );
  }

  if (data.reason === "expired") {
    return (
      <Link href="/app/settings">
        <Badge variant="warning" className="cursor-pointer gap-1.5">
          <Dot className="bg-amber-500" />
          Reconnect Google
        </Badge>
      </Link>
    );
  }

  return (
    <Link href="/app/settings">
      <Badge variant="destructive" className="cursor-pointer gap-1.5">
        <Dot className="bg-destructive" />
        Connect Google
      </Badge>
    </Link>
  );
}

function Dot({ className }: { className?: string }) {
  return <span className={cn("inline-block size-2 rounded-full", className)} />;
}
