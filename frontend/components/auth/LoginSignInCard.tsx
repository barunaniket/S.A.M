"use client";

import { Lock, Shield, ShieldCheck, User, Users } from "lucide-react";
import { ConnectGoogleButton } from "@/components/auth/ConnectGoogleButton";

export function LoginSignInCard() {
  return (
    <section className="flex w-full items-center justify-center">
      <div className="w-full max-w-md rounded-2xl border border-border bg-card p-8 shadow-sm lg:p-10">
        <div className="text-center">
          <div className="mx-auto grid size-12 place-items-center rounded-full bg-muted text-foreground">
            <User className="size-5" strokeWidth={2} />
          </div>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-foreground">
            Sign in as Teacher-in-Charge
          </h2>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-muted-foreground">
            Connect your Google Calendar to automate scheduling, send invites,
            and avoid conflicts on your behalf.
          </p>
        </div>

        <div className="mt-7">
          <ConnectGoogleButton
            className="h-11 w-full rounded-md text-sm font-medium"
            label="Connect Google Calendar"
          />
        </div>

        <div className="mt-8 flex items-center gap-3">
          <span className="h-px flex-1 bg-border" />
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Why we need access
          </span>
          <span className="h-px flex-1 bg-border" />
        </div>

        <ul className="mt-6 space-y-4">
          <BenefitRow
            icon={<Users className="size-4" strokeWidth={2} />}
            lead="Only Teacher-in-Charge (SPOC) logs in."
            detail="This ensures secure and controlled access."
          />
          <BenefitRow
            icon={<Shield className="size-4" strokeWidth={2} />}
            lead="Your data is safe with us."
            detail="We use encrypted tokens to protect your information."
          />
          <BenefitRow
            icon={<Lock className="size-4" strokeWidth={2} />}
            lead="You're always in control."
            detail="Disconnect anytime from Settings."
          />
        </ul>

        <div className="mt-8 flex items-center justify-center gap-2 border-t border-border pt-5 text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5" />
          Trusted by faculty. Built for efficiency.
        </div>
      </div>
    </section>
  );
}

function BenefitRow({
  icon,
  lead,
  detail,
}: {
  icon: React.ReactNode;
  lead: string;
  detail: string;
}) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-muted text-foreground">
        {icon}
      </span>
      <div className="leading-snug">
        <p className="text-[13px] font-semibold text-foreground">{lead}</p>
        <p className="mt-1 text-[12px] text-muted-foreground">{detail}</p>
      </div>
    </li>
  );
}
