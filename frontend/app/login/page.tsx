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
    <main className="min-h-screen bg-slate-100 p-4 lg:p-8">
      <div className="mx-auto grid h-full min-h-[calc(100vh-4rem)] w-full max-w-7xl overflow-hidden rounded-3xl bg-card shadow-xl ring-1 ring-border lg:grid-cols-[1.4fr_1fr]">
        <LoginHero />
        <LoginSignInCard />
      </div>
    </main>
  );
}
