"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";

export type SamRole =
  | "ADMIN"
  | "FACULTY"
  | "STUDENT"
  | "SUPER_ADMIN"
  | "BOOKING_AUTHORITY";

type RoleGuardProps = {
  /** Roles permitted to view children. SUPER_ADMIN always passes. */
  allow: SamRole[];
  children: React.ReactNode;
  /** Where to send unauthorised users. Defaults to the chat home. */
  redirectTo?: string;
};

/**
 * Client-side route guard. Renders children only when the authenticated user
 * holds a permitted role. Redirects elsewhere otherwise. SUPER_ADMIN passes
 * every check.
 *
 * Note: this is convenience UX, not a security boundary — every backend
 * route is independently protected via `Depends(require_roles(...))`.
 */
export function RoleGuard({ allow, children, redirectTo = "/app" }: RoleGuardProps) {
  const { user, ready, isAuthed } = useAuth();
  const router = useRouter();

  const role = (user?.role || "").toUpperCase() as SamRole | "";
  const permitted =
    !!role && (role === "SUPER_ADMIN" || allow.includes(role as SamRole));

  useEffect(() => {
    if (!ready) return;
    if (!isAuthed) {
      router.replace("/login");
      return;
    }
    if (!permitted) {
      router.replace(redirectTo);
    }
  }, [ready, isAuthed, permitted, redirectTo, router]);

  if (!ready || !isAuthed || !permitted) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  return <>{children}</>;
}
