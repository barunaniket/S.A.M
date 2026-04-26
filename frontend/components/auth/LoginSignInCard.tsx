"use client";

import {
  ShieldCheck,
  Settings,
  Shield,
  User,
  UserCheck,
} from "lucide-react";
import { ConnectGoogleButton } from "@/components/auth/ConnectGoogleButton";

export function LoginSignInCard() {
  return (
    <section className="flex w-full items-center justify-center bg-background p-6 lg:p-10">
      <div className="w-full max-w-md">
        <div className="text-center">
          <div className="mx-auto grid size-11 place-items-center rounded-full bg-blue-100 text-blue-600">
            <User className="size-5" />
          </div>
          <h2 className="mt-5 text-xl font-semibold tracking-tight text-foreground">
            Sign in as Teacher-in-Charge
          </h2>
          <p className="mx-auto mt-2 max-w-xs text-sm text-muted-foreground">
            Connect your Google Calendar to automate scheduling, send invites,
            and avoid conflicts on your behalf.
          </p>
        </div>

        <div className="mt-6">
          <ConnectGoogleButton
            className="w-full bg-gradient-to-r from-blue-500 to-blue-600 text-white shadow-md hover:from-blue-600 hover:to-blue-700"
            label="Connect Google Calendar"
          />
        </div>

        <div className="mt-8">
          <p className="text-center text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Why we need this:
          </p>
          <ul className="mt-5 space-y-4">
            <BenefitRow
              icon={<UserCheck className="size-4" />}
              lead="Only Teacher-in-Charge (SPOC) logs in."
              detail="This ensures secure and controlled access."
            />
            <BenefitRow
              icon={<Shield className="size-4" />}
              lead="Your data is safe with us."
              detail="We use industry-standard layers to protect your information."
            />
            <BenefitRow
              icon={<Settings className="size-4" />}
              lead="You're always in control."
              detail="Disconnect anytime from Settings."
            />
          </ul>
        </div>

        <p className="mt-10 flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5 text-emerald-600" />
          Trusted by Faculty. Built for efficiency.
        </p>
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
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-blue-100 text-blue-600">
        {icon}
      </span>
      <div className="leading-snug">
        <p className="text-sm font-semibold text-foreground">{lead}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p>
      </div>
    </li>
  );
}
