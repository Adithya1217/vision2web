"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore } from "react";

import { api, getToken, setToken, subscribeToken } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | undefined;
  loading: boolean;
  authenticated: boolean;
  can: (perm: string) => boolean;
  login: (email: string, password: string) => Promise<void>;
  acceptToken: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const router = useRouter();
  // undefined on the server (not yet known), string | null in the browser.
  const token = useSyncExternalStore<string | null | undefined>(subscribeToken, getToken, () => undefined);
  const ready = token !== undefined;

  useEffect(() => {
    const onUnauthorized = () => {
      qc.clear();
      router.replace("/login");
    };
    window.addEventListener("msme:unauthorized", onUnauthorized);
    return () => window.removeEventListener("msme:unauthorized", onUnauthorized);
  }, [qc, router]);

  const meQuery = useQuery({
    queryKey: ["me", token],
    queryFn: () => api.get<Me>("/auth/me"),
    enabled: !!token,
    staleTime: 5 * 60_000,
  });

  const acceptToken = useCallback(
    (t: string) => {
      qc.clear();
      setToken(t);
    },
    [qc],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api.post<{ access_token: string }>("/auth/login", { email, password });
      acceptToken(res.access_token);
    },
    [acceptToken],
  );

  const logout = useCallback(() => {
    setToken(null);
    qc.clear();
    router.replace("/login");
  }, [qc, router]);

  const value = useMemo<AuthState>(() => {
    const perms = new Set(meQuery.data?.permissions ?? []);
    return {
      me: meQuery.data,
      loading: !ready || (!!token && meQuery.isLoading),
      authenticated: !!token && !!meQuery.data,
      can: (perm: string) => perms.has(perm),
      login,
      acceptToken,
      logout,
    };
  }, [meQuery.data, meQuery.isLoading, ready, token, login, acceptToken, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
