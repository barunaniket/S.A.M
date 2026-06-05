"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  Calendar,
  ClipboardCheck,
  ClipboardList,
  DoorOpen,
  FileText,
  LayoutDashboard,
  MessageSquare,
  Megaphone,
  Settings,
  Upload,
  Users,
  UserSquare2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";

type Role = "ADMIN" | "FACULTY" | "STUDENT" | "SUPER_ADMIN" | "BOOKING_AUTHORITY";
type SidebarItem = {
  href: string;
  label: string;
  icon: typeof Calendar;
  exact?: boolean;
  /** Roles permitted to see this item. Omit / empty array = visible to all. */
  roles?: Role[];
};

const items: SidebarItem[] = [
  { href: "/app", label: "Chat", icon: MessageSquare, exact: true },
  { href: "/app/meetings", label: "Meetings", icon: Calendar },
  { href: "/app/faculty", label: "Faculty", icon: UserSquare2 },
  { href: "/app/groups", label: "Groups", icon: Users },
  { href: "/app/broadcasts", label: "Broadcasts", icon: Megaphone },
  { href: "/app/timetable/upload", label: "My timetable", icon: Upload, roles: ["FACULTY", "ADMIN"] },
  { href: "/app/admin/tasks", label: "Task assignments", icon: ClipboardList, roles: ["ADMIN"] },
  { href: "/app/faculty/attendance", label: "Attendance", icon: ClipboardCheck, roles: ["FACULTY", "ADMIN"] },
  { href: "/app/faculty/assignments", label: "Assignments", icon: FileText, roles: ["FACULTY", "ADMIN"] },
  { href: "/app/booking/queue", label: "Booking queue", icon: DoorOpen, roles: ["BOOKING_AUTHORITY"] },
  { href: "/app/super-admin/materials", label: "Course materials", icon: BookOpen, roles: ["FACULTY", "ADMIN"] },
  { href: "/app/super-admin", label: "Super admin", icon: LayoutDashboard, roles: ["SUPER_ADMIN"] },
  { href: "/app/settings", label: "Settings", icon: Settings },
];

function visibleItems(role: string | null | undefined): SidebarItem[] {
  const r = (role || "").toUpperCase();
  // SUPER_ADMIN sees everything; otherwise filter by item.roles.
  if (r === "SUPER_ADMIN") return items;
  return items.filter((it) => !it.roles || it.roles.length === 0 || it.roles.includes(r as Role));
}

export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();

  return (
    <aside className="flex h-screen w-60 flex-col border-r border-border bg-card">
      <div className="flex h-14 items-center gap-2 border-b border-border px-5">
        <div className="grid size-7 place-items-center rounded-md bg-primary text-primary-foreground font-bold">
          S
        </div>
        <span className="font-semibold tracking-tight">S.A.M</span>
      </div>

      <nav className="flex-1 space-y-0.5 p-3">
        {visibleItems(user?.role).map((item) => {
          const active = item.exact
            ? pathname === item.href
            : pathname?.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                active
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {user && (
        <div className="border-t border-border p-3">
          <div className="flex items-center gap-3 rounded-md p-2">
            {user.picture ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={user.picture}
                alt={user.name}
                className="size-8 rounded-full"
              />
            ) : (
              <div className="grid size-8 place-items-center rounded-full bg-muted text-xs font-medium">
                {user.name?.[0]?.toUpperCase() ?? "?"}
              </div>
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{user.name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {user.email}
              </p>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
