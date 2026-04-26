"use client";

import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import type { AgendaResponse } from "@/lib/types";

function todayIso(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function useAgenda(date?: string) {
  const target = date ?? todayIso();
  return useSWR<AgendaResponse>(
    ["agenda", target],
    () => apiFetch<AgendaResponse>(`/api/v1/agenda?date=${target}`),
    { revalidateOnFocus: false, refreshInterval: 60_000 },
  );
}
