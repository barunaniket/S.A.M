"use client";

import {
  Bell,
  CalendarClock,
  CheckCircle2,
  Lock,
  ShieldAlert,
  Sparkles,
} from "lucide-react";

export function LoginHero() {
  return (
    <aside className="relative hidden flex-col justify-between overflow-hidden bg-blue-50/60 p-10 lg:flex xl:p-12">
      <div
        aria-hidden
        className="pointer-events-none absolute -left-24 -top-24 size-[28rem] rounded-full bg-blue-200/50 blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-32 -right-24 size-[32rem] rounded-full bg-indigo-200/40 blur-3xl"
      />

      <header className="relative flex items-center gap-2.5">
        <div className="grid size-9 place-items-center rounded-xl bg-blue-600 text-sm font-bold text-white shadow-sm">
          S
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-tight text-foreground">
            S.A.M
          </p>
          <p className="text-[10px] text-muted-foreground">
            Smart Administrative Messenger
          </p>
        </div>
      </header>

      <div className="relative flex flex-1 flex-col justify-center gap-10 py-8">
        <div>
          <h1 className="text-6xl font-bold leading-[1.02] tracking-tight text-foreground">
            Simplify Faculty
            <br />
            Scheduling
          </h1>
          <p className="mt-5 max-w-md text-base text-muted-foreground">
            Automate meetings, avoid conflicts, and manage schedules
            effortlessly.
          </p>
        </div>

        <HeroIllustration />

        <div className="grid grid-cols-3 gap-3">
          <FeatureCard
            icon={<CalendarClock className="size-4 text-blue-600" />}
            title="Smart Scheduling"
            subtitle="Find the best slot in seconds."
          />
          <FeatureCard
            icon={<ShieldAlert className="size-4 text-amber-600" />}
            title="Conflict Detection"
            subtitle="Catch overlaps automatically."
          />
          <FeatureCard
            icon={<Bell className="size-4 text-indigo-600" />}
            title="Centralized Updates"
            subtitle="One source of truth for all."
          />
        </div>
      </div>

      <p className="relative flex items-center gap-2 text-xs text-muted-foreground">
        <Lock className="size-3.5 shrink-0" />
        <span>
          Built with security &amp; privacy in mind. We only access your
          calendar to create and manage events on your behalf.
        </span>
      </p>
    </aside>
  );
}

function FeatureCard({
  icon,
  title,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-white/80 p-3 shadow-sm backdrop-blur-sm">
      <div className="flex items-center gap-2">
        <span className="grid size-7 place-items-center rounded-lg bg-blue-50">
          {icon}
        </span>
        <p className="text-[12px] font-semibold text-foreground">{title}</p>
      </div>
      <p className="mt-1.5 text-[10px] leading-snug text-muted-foreground">
        {subtitle}
      </p>
    </div>
  );
}

function HeroIllustration() {
  return (
    <div className="relative mx-auto h-56 w-full max-w-md">
      <div
        aria-hidden
        className="absolute left-1/2 top-1/2 size-56 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-200/40 blur-2xl"
      />

      <div className="absolute left-2 top-2 w-56 rounded-2xl border border-border bg-card p-4 shadow-lg">
        <div className="flex items-center gap-2 rounded-full bg-blue-50 px-2.5 py-1 w-fit">
          <Sparkles className="size-3 text-blue-600" />
          <span className="text-[10px] font-semibold text-blue-700">
            AI Assistant
          </span>
        </div>
        <p className="mt-3 text-[10px] text-muted-foreground">
          Finding the best slot…
        </p>
        <div className="mt-3 space-y-2">
          <div className="rounded-lg bg-blue-50 p-2">
            <div className="h-1.5 w-3/4 rounded-full bg-blue-200" />
            <div className="mt-1.5 h-1.5 w-1/2 rounded-full bg-blue-200/60" />
          </div>
          <div className="rounded-lg bg-amber-50 p-2">
            <div className="h-1.5 w-2/3 rounded-full bg-amber-200" />
            <div className="mt-1.5 h-1.5 w-2/5 rounded-full bg-amber-200/60" />
          </div>
        </div>
      </div>

      <FloatingChip
        className="right-2 top-4"
        icon={<CalendarClock className="size-3 text-blue-600" />}
        title="Smart Scheduling"
      />
      <FloatingChip
        className="bottom-12 right-0"
        icon={<ShieldAlert className="size-3 text-rose-600" />}
        title="No Conflicts"
      />
      <FloatingChip
        className="bottom-2 right-10"
        icon={<CheckCircle2 className="size-3 text-emerald-600" />}
        title="Confirmed"
      />
    </div>
  );
}

function FloatingChip({
  className,
  icon,
  title,
}: {
  className?: string;
  icon: React.ReactNode;
  title: string;
}) {
  return (
    <div
      className={`absolute flex items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-1.5 text-[10px] font-semibold text-foreground shadow-md ${className ?? ""}`}
    >
      {icon}
      {title}
    </div>
  );
}
