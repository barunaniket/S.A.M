"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  clearToken,
  getToken,
  getUser,
  isExpired,
  setToken as persistToken,
  setUser as persistUser,
} from "@/lib/auth";
import type { SamUser } from "@/lib/types";

type AuthSnapshot = {
  user: SamUser | null;
  token: string | null;
  ready: boolean;
};

type AuthApi = AuthSnapshot & {
  isAuthed: boolean;
  login: (token: string, user: SamUser) => void;
  logout: () => void;
};

// ---------------------------------------------------------------------------
// Module-level store (singleton). No React Context — so consumers don't need
// any provider in scope, which sidesteps Next.js client/server boundary edge
// cases that were leaving useContext null at render time.
// ---------------------------------------------------------------------------
let snapshot: AuthSnapshot = { user: null, token: null, ready: false };
const listeners = new Set<(s: AuthSnapshot) => void>();
let initialized = false;

function emit(next: AuthSnapshot) {
  snapshot = next;
  listeners.forEach((l) => l(next));
}

function ensureInitialized() {
  if (initialized || typeof window === "undefined") return;
  initialized = true;
  const token = getToken();
  const user = getUser();
  if (token && !isExpired(token) && user) {
    emit({ user, token, ready: true });
  } else {
    if (token) clearToken();
    emit({ user: null, token: null, ready: true });
  }
}

// ---------------------------------------------------------------------------
// useAuth: subscribes the calling component to the singleton.
// Works during SSR (returns the idle snapshot) and on the client.
// ---------------------------------------------------------------------------
export function useAuth(): AuthApi {
  const router = useRouter();
  const [state, setState] = useState<AuthSnapshot>(snapshot);

  useEffect(() => {
    ensureInitialized();
    setState(snapshot);
    const onChange = (next: AuthSnapshot) => setState(next);
    listeners.add(onChange);
    return () => {
      listeners.delete(onChange);
    };
  }, []);

  const login = useCallback((token: string, user: SamUser) => {
    persistToken(token);
    persistUser(user);
    emit({ token, user, ready: true });
  }, []);

  const logout = useCallback(() => {
    clearToken();
    emit({ token: null, user: null, ready: true });
    router.push("/login");
  }, [router]);

  return {
    ...state,
    isAuthed: !!state.token && !!state.user,
    login,
    logout,
  };
}
