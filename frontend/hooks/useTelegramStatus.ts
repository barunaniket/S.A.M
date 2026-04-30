"use client";

import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import type { TelegramStatus } from "@/lib/types";

export function useTelegramStatus() {
  return useSWR<TelegramStatus>(
    "telegram-status",
    () => apiFetch<TelegramStatus>("/api/v1/me/telegram/status"),
    { refreshInterval: 60_000, revalidateOnFocus: true },
  );
}
