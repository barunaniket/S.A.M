"use client";

import { useState } from "react";
import { LogOut } from "lucide-react";
import { OAuthStatusPill } from "@/components/auth/OAuthStatusPill";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";

export function Header({ title }: { title?: string }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-background/80 px-6 backdrop-blur">
      <div className="text-sm font-medium text-muted-foreground">
        {title ?? "Chat"}
      </div>

      <div className="flex items-center gap-3">
        <OAuthStatusPill />

        <div className="relative">
          <button
            onClick={() => setOpen((v) => !v)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            className="grid size-9 place-items-center rounded-full hover:bg-muted"
            aria-label="Account menu"
          >
            {user?.picture ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={user.picture}
                alt={user.name}
                className="size-8 rounded-full"
              />
            ) : (
              <div className="grid size-8 place-items-center rounded-full bg-muted text-xs font-medium">
                {user?.name?.[0]?.toUpperCase() ?? "?"}
              </div>
            )}
          </button>

          {open && (
            <div className="absolute right-0 top-11 z-50 w-56 rounded-md border border-border bg-popover p-1 shadow-md">
              <div className="px-3 py-2 text-xs">
                <p className="truncate font-medium">{user?.name}</p>
                <p className="truncate text-muted-foreground">{user?.email}</p>
              </div>
              <div className="my-1 h-px bg-border" />
              <Button
                variant="ghost"
                size="sm"
                className="w-full justify-start gap-2"
                onClick={logout}
              >
                <LogOut className="size-4" />
                Sign out
              </Button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
