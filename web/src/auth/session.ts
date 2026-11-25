import type { AuthenticatedPrincipalResponse } from "../api/types";

export interface StoredAuthSession {
  readonly accessToken: string;
  readonly refreshToken: string | null;
  readonly expiresAtMs: number | null;
  readonly principal: AuthenticatedPrincipalResponse;
}

const SESSION_STORAGE_KEY = "brew.auth.session.v1";
const EXPIRY_SAFETY_BUFFER_MS = 5_000;

function getSessionStorageSafe(): Storage | null {
  try {
    if (typeof window !== "undefined" && window.sessionStorage) {
      return window.sessionStorage;
    }
  } catch {
    return null;
  }
  return null;
}

export function decodeJwtExpiryMs(token: string): number | null {
  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }
  const payloadSegment = parts[1];
  if (!payloadSegment) {
    return null;
  }
  try {
    const normalized = payloadSegment.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const decoded = JSON.parse(globalThis.atob(padded)) as Record<string, unknown>;
    const exp = decoded["exp"];
    if (typeof exp === "number" && Number.isFinite(exp)) {
      return exp * 1000;
    }
  } catch {
    return null;
  }
  return null;
}

export function isSessionExpired(
  session: StoredAuthSession,
  nowMs: number = Date.now(),
): boolean {
  if (session.expiresAtMs === null) {
    return false;
  }
  return nowMs >= session.expiresAtMs - EXPIRY_SAFETY_BUFFER_MS;
}

export function loadStoredSession(): StoredAuthSession | null {
  const storage = getSessionStorageSafe();
  if (!storage) {
    return null;
  }
  const raw = storage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const accessToken = parsed["accessToken"];
    const refreshToken = parsed["refreshToken"];
    const expiresAtMs = parsed["expiresAtMs"];
    const principal = parsed["principal"] as Record<string, unknown> | undefined;

    if (
      typeof accessToken !== "string" ||
      !accessToken.trim() ||
      !principal ||
      typeof principal["user_id"] !== "string" ||
      typeof principal["auth_provider"] !== "string"
    ) {
      storage.removeItem(SESSION_STORAGE_KEY);
      return null;
    }

    return {
      accessToken,
      refreshToken: typeof refreshToken === "string" ? refreshToken : null,
      expiresAtMs: typeof expiresAtMs === "number" ? expiresAtMs : null,
      principal: {
        user_id: principal["user_id"],
        display_name:
          typeof principal["display_name"] === "string" ? principal["display_name"] : null,
        custom_display_name:
          typeof principal["custom_display_name"] === "string"
            ? principal["custom_display_name"]
            : null,
        account_display_name:
          typeof principal["account_display_name"] === "string"
            ? principal["account_display_name"]
            : null,
        auth_provider: principal["auth_provider"],
      },
    };
  } catch {
    storage.removeItem(SESSION_STORAGE_KEY);
    return null;
  }
}

export function saveStoredSession(session: StoredAuthSession): void {
  const storage = getSessionStorageSafe();
  if (!storage) {
    return;
  }
  storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredSession(): void {
  const storage = getSessionStorageSafe();
  if (!storage) {
    return;
  }
  storage.removeItem(SESSION_STORAGE_KEY);
}
