"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  CalendarRange,
  FileSearch,
  LayoutDashboard,
  ShieldCheck,
  SlidersHorizontal,
  Users2,
} from "lucide-react";
import { RoleGuard, type SamRole } from "@/components/auth/RoleGuard";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  exact?: boolean;
  roles: SamRole[];
};

const items: NavItem[] = [
  { href: "/app/super-admin",          label: "Overview",          icon: LayoutDashboard,  exact: true, roles: ["SUPER_ADMIN"] },
  { href: "/app/super-admin/users",    label: "Users",             icon: ShieldCheck,                  roles: ["SUPER_ADMIN"] },
  { href: "/app/super-admin/groups",   label: "Groups",            icon: Users2,                       roles: ["SUPER_ADMIN"] },
  { href: "/app/super-admin/calendar", label: "Academic calendar", icon: CalendarRange,                roles: ["SUPER_ADMIN"] },
  { href: "/app/super-admin/settings", label: "Org settings",      icon: SlidersHorizontal,            roles: ["SUPER_ADMIN"] },
  { href: "/app/super-admin/materials",label: "Course materials",  icon: BookOpen,                     roles: ["SUPER_ADMIN", "FACULTY", "ADMIN"] },
  { href: "/app/super-admin/audit",    label: "Audit log",         icon: FileSearch,                   roles: ["SUPER_ADMIN"] },
];

export default function SuperAdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useAuth();
  const role = (user?.role || "").toUpperCase() as SamRole | "";
  const visible = role === "SUPER_ADMIN"
    ? items
    : items.filter((it) => it.roles.includes(role as SamRole));

  // Gate by the roles declared on the nav item for the current path, so the
  // guard always matches what the sidebar advertises. Most of this section is
  // SUPER_ADMIN-only; only Course materials opens up to FACULTY/ADMIN. Unknown
  // sub-paths fall back to the strictest setting.
  const activeItem = items.find((it) =>
    it.exact ? pathname === it.href : pathname?.startsWith(it.href),
  );
  const allow = activeItem?.roles ?? (["SUPER_ADMIN"] as SamRole[]);

  return (
    <RoleGuard allow={allow}>
      <div className="flex h-full overflow-hidden">
        {/* Sub-sidebar */}
        <aside className="hidden w-56 flex-col border-r border-border bg-card md:flex">
          <div className="border-b border-border px-4 py-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {role === "SUPER_ADMIN" ? "Super Admin" : "Workspace"}
          </div>
          <nav className="flex-1 space-y-0.5 p-2">
            {visible.map((item) => {
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
        </aside>

        {/* Mobile horizontal scroll nav */}
        <div className="md:hidden border-b border-border">
          <nav className="flex gap-1 overflow-x-auto p-2">
            {visible.map((item) => {
              const active = item.exact
                ? pathname === item.href
                : pathname?.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex shrink-0 items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    active
                      ? "bg-muted text-foreground"
                      : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )}
                >
                  <Icon className="size-3.5" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </RoleGuard>
  );
}
