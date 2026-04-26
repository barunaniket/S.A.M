"use client";

import {
  CalendarClock,
  CheckCircle2,
  Lock,
  Shield,
  Sparkles,
  Users,
} from "lucide-react";

export function LoginHero() {
  return (
    <aside className="flex flex-col justify-between gap-12">
      <header className="flex items-center gap-2.5">
        <div className="grid size-9 place-items-center rounded-md bg-primary font-bold text-primary-foreground">
          S
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-tight text-foreground">
            S.A.M
          </p>
          <p className="text-[11px] text-muted-foreground">
            Smart Administrative Messenger
          </p>
        </div>
      </header>

      <div className="space-y-10">
        <div>
          <h1 className="text-5xl font-semibold leading-[1.05] tracking-tight text-foreground xl:text-[3.5rem]">
            Simplify Faculty
            <br />
            Scheduling
          </h1>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-muted-foreground">
            Automate meetings, avoid conflicts, and manage schedules
            effortlessly.
          </p>
        </div>

        <HeroIllustration />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <FeatureCard
            icon={<CalendarClock className="size-4" />}
            title="Smart Scheduling"
            subtitle="Find the best time for meetings automatically."
          />
          <FeatureCard
            icon={<Shield className="size-4" />}
            title="Conflict Detection"
            subtitle="Catch overlaps before they happen."
          />
          <FeatureCard
            icon={<Users className="size-4" />}
            title="Centralized Updates"
            subtitle="Send invites and updates from one place."
          />
        </div>
      </div>

      <div className="flex items-start gap-3 rounded-lg border border-border bg-card/70 px-4 py-3 backdrop-blur">
        <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
          <Lock className="size-3.5" />
        </span>
        <p className="text-xs leading-relaxed text-muted-foreground">
          Built with security &amp; privacy in mind. We only access your calendar
          to create and manage events on your behalf.
        </p>
      </div>
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
    <div className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-foreground/15">
      <div className="flex items-center gap-2.5">
        <span className="grid size-7 place-items-center rounded-md bg-muted text-foreground">
          {icon}
        </span>
        <p className="text-[13px] font-semibold tracking-tight text-foreground">
          {title}
        </p>
      </div>
      <p className="mt-2 text-[12px] leading-snug text-muted-foreground">
        {subtitle}
      </p>
    </div>
  );
}

function HeroIllustration() {
  return (
    <div className="relative mx-auto h-64 w-full max-w-lg">
      <div
        aria-hidden
        className="absolute inset-x-10 inset-y-6 rounded-3xl bg-blue-500/[0.06] blur-2xl"
      />

      {/* Calendar window mockup */}
      <div className="absolute left-8 top-2 flex w-[78%] overflow-hidden rounded-xl border border-border bg-card shadow-sm">
        {/* Window chrome */}
        <div className="flex w-9 flex-col items-center gap-3 border-r border-border bg-muted/60 py-3">
          <div className="flex flex-col gap-1">
            <span className="size-1.5 rounded-full bg-foreground/20" />
            <span className="size-1.5 rounded-full bg-foreground/20" />
            <span className="size-1.5 rounded-full bg-foreground/20" />
          </div>
          <CalendarClock className="size-3.5 text-muted-foreground" />
          <Users className="size-3.5 text-muted-foreground" />
          <Sparkles className="size-3.5 text-muted-foreground" />
        </div>

        {/* Calendar body */}
        <div className="relative flex-1 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="h-2 w-16 rounded-full bg-muted" />
            <div className="flex gap-1">
              <span className="size-1.5 rounded-full bg-muted" />
              <span className="size-1.5 rounded-full bg-muted" />
            </div>
          </div>
          <div className="grid grid-cols-4 gap-1">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-3 rounded-sm bg-muted/70" />
            ))}
          </div>
          <div className="relative mt-1.5 grid grid-cols-4 gap-1">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-24 rounded-sm bg-muted/40" />
            ))}

            {/* Event chips */}
            <div className="absolute left-1 top-1 w-[44%] rounded-md border border-blue-500/20 bg-blue-50 px-2 py-1.5">
              <p className="text-[8px] font-semibold leading-tight text-blue-900">
                Department
                <br />
                Meeting
              </p>
              <p className="mt-0.5 text-[7px] text-blue-700/70">10:00 AM</p>
            </div>
            <div className="absolute left-[46%] top-6 w-[36%] rounded-md border border-violet-500/20 bg-violet-50 px-2 py-1.5">
              <p className="text-[8px] font-semibold leading-tight text-violet-900">
                Class Review
              </p>
              <p className="mt-0.5 text-[7px] text-violet-700/70">11:30 AM</p>
            </div>
            <div className="absolute left-[26%] bottom-1 w-[42%] rounded-md border border-amber-500/20 bg-amber-50 px-2 py-1.5">
              <p className="text-[8px] font-semibold leading-tight text-amber-900">
                Curriculum
                <br />
                Discussion
              </p>
              <p className="mt-0.5 text-[7px] text-amber-700/70">2:00 PM</p>
            </div>
          </div>
        </div>
      </div>

      {/* AI Assistant card */}
      <div className="absolute -left-2 bottom-2 w-44 rounded-lg border border-border bg-card p-3 shadow-sm">
        <div className="flex items-center gap-1.5">
          <Sparkles className="size-3 text-foreground" />
          <span className="text-[11px] font-semibold tracking-tight text-foreground">
            AI Assistant
          </span>
        </div>
        <p className="mt-1.5 text-[10px] leading-snug text-muted-foreground">
          Finding the best time for everyone…
        </p>
        <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-muted">
          <div className="h-full w-2/3 rounded-full bg-foreground/80" />
        </div>
      </div>

      {/* No conflicts pill */}
      <div className="absolute right-2 top-8 flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1.5 shadow-sm">
        <CheckCircle2 className="size-3.5 text-emerald-600" />
        <span className="text-[10px] font-semibold tracking-tight text-foreground">
          No Conflicts
        </span>
      </div>

      {/* Confirmed pill */}
      <div className="absolute bottom-6 right-4 flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1.5 shadow-sm">
        <Shield className="size-3.5 text-foreground" />
        <span className="text-[10px] font-semibold tracking-tight text-foreground">
          Confirmed
        </span>
      </div>
    </div>
  );
}
