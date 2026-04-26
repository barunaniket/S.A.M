"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { LoadingDots } from "@/components/common/LoadingDots";

export default function RootPage() {
  const router = useRouter();
  const { ready, isAuthed } = useAuth();

  useEffect(() => {
    if (!ready) return;
    router.replace(isAuthed ? "/app" : "/login");
  }, [ready, isAuthed, router]);

  return (
    <div className="grid h-screen place-items-center">
      <LoadingDots />
    </div>
  );
}
