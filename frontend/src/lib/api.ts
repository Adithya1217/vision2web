export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const TOKEN_KEY = "msme.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: string,
    public extra?: unknown,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}

let memoryToken: string | null = null;

export function setToken(token: string | null) {
  memoryToken = token;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token lives in memory for this tab only */
  }
  window.dispatchEvent(new Event("msme:token"));
}

export function subscribeToken(onChange: () => void) {
  window.addEventListener("msme:token", onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener("msme:token", onChange);
    window.removeEventListener("storage", onChange);
  };
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query) {
  const url = new URL(API_URL + path);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
  }
  return url.toString();
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((x) => x !== "body").join(".");
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  return "Request failed";
}

async function request<T>(method: string, path: string, opts: { body?: unknown; query?: Query; key?: string } = {}) {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["Idempotency-Key"] = opts.key ?? crypto.randomUUID();
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.", "network");
  }
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    setToken(null);
    if (typeof window !== "undefined") window.dispatchEvent(new Event("msme:unauthorized"));
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, describe(data?.detail), data?.code, data?.extra);
  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, { query }),
  post: <T>(path: string, body?: unknown, key?: string) => request<T>("POST", path, { body, key }),
  put: <T>(path: string, body?: unknown, key?: string) => request<T>("PUT", path, { body, key }),
  patch: <T>(path: string, body?: unknown, key?: string) => request<T>("PATCH", path, { body, key }),
  delete: <T>(path: string, key?: string) => request<T>("DELETE", path, { key }),
};

/**
 * Keeps one Idempotency-Key per logical submission: retrying the *same* payload (after a timeout or
 * network error) reuses the key so the server can replay instead of applying the change twice. A changed
 * payload, or a successful submission, starts a new key.
 */
export function createSubmitter() {
  let lastBody: string | null = null;
  let key: string = crypto.randomUUID();
  return {
    keyFor(body: unknown): string {
      const serialized = JSON.stringify(body ?? null);
      if (serialized !== lastBody) {
        key = crypto.randomUUID();
        lastBody = serialized;
      }
      return key;
    },
    done() {
      lastBody = null;
      key = crypto.randomUUID();
    },
  };
}
