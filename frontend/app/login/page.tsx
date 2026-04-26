"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { LoginHero } from "@/components/auth/LoginHero";
import { LoginSignInCard } from "@/components/auth/LoginSignInCard";
import { useAuth } from "@/hooks/useAuth";

export default function LoginPage() {
  const router = useRouter();
  const { ready, isAuthed } = useAuth();

  useEffect(() => {
    if (ready && isAuthed) router.replace("/app");
  }, [ready, isAuthed, router]);

  return (
    <main className="relative min-h-screen overflow-hidden bg-muted/40">
      <div
        aria-hidden
        className="pointer-events-none absolute -left-40 top-[-20%] h-[40rem] w-[40rem] rounded-full bg-blue-500/[0.08] blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-40 bottom-[-30%] h-[40rem] w-[40rem] rounded-full bg-primary/[0.06] blur-3xl"
      />

      <div className="relative mx-auto flex min-h-screen w-full max-w-7xl items-center px-6 py-12 lg:px-12">
        <div className="grid w-full gap-12 lg:grid-cols-[1.15fr_1fr] lg:gap-20">
          <LoginHero />
          <LoginSignInCard />
        </div>
      </div>
    </main>
  );
}
