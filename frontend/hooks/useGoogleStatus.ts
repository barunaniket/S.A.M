"use client";

import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import type { GoogleStatus } from "@/lib/types";

export function useGoogleStatus() {
  return useSWR<GoogleStatus>(
    "google-status",
    () => apiFetch<GoogleStatus>("/api/v1/me/google-status"),
    { refreshInterval: 60_000, revalidateOnFocus: true },
  );
}
