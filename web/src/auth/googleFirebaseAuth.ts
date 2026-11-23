import type { FirebaseClientConfigResponse } from "../api/types";
import { decodeJwtExpiryMs } from "./session";

export interface VerifiedSignInTokens {
  readonly idToken: string;
  readonly refreshToken: string | null;
  readonly expiresAtMs: number | null;
}

interface GoogleCredentialResponse {
  readonly credential?: string;
}

interface GoogleAccountsIdApi {
  initialize: (config: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
    auto_select?: boolean;
    cancel_on_tap_outside?: boolean;
  }) => void;
  prompt: (momentListener?: (notification: {
    isNotDisplayed: () => boolean;
    isSkippedMoment: () => boolean;
    getNotDisplayedReason?: () => string;
  }) => void) => void;
  renderButton: (
    parent: HTMLElement,
    options: {
      theme?: "outline" | "filled_blue" | "filled_black";
      size?: "large" | "medium" | "small";
      text?: "signin_with" | "continue_with";
      shape?: "pill" | "rectangular";
      width?: number;
    },
  ) => void;
}

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: GoogleAccountsIdApi;
      };
    };
  }
}

const GIS_SCRIPT_SRC = "https://accounts.google.com/gsi/client";
const AUTH_TIMEOUT_MS = 10_000;

let gisScriptPromise: Promise<void> | null = null;

export function loadGoogleIdentityServicesScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Browser window is unavailable."));
  }
  if (window.google?.accounts?.id) {
    return Promise.resolve();
  }
  if (gisScriptPromise) {
    return gisScriptPromise;
  }

  gisScriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${GIS_SCRIPT_SRC}"]`,
    );
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error("Unable to load Google Sign-In script.")),
        { once: true },
      );
      return;
    }

    const script = document.createElement("script");
    script.src = GIS_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      gisScriptPromise = null;
      reject(new Error("Unable to load Google Sign-In script."));
    };
    document.head.appendChild(script);
  });

  return gisScriptPromise;
}

/**
 * Exchange a Google OIDC credential for a Firebase Authentication ID token + refresh token
 * when Firebase Authentication is configured on the server.
 */
export async function exchangeGoogleCredentialWithFirebase(
  googleIdToken: string,
  firebase: FirebaseClientConfigResponse,
): Promise<VerifiedSignInTokens> {
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), AUTH_TIMEOUT_MS);

  try {
    const endpoint = `https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=${encodeURIComponent(firebase.api_key)}`;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        postBody: `id_token=${encodeURIComponent(googleIdToken)}&providerId=google.com`,
        requestUri: window.location.origin,
        returnIdpCredential: true,
        returnSecureToken: true,
      }),
    });

    if (!response.ok) {
      throw new Error(`Firebase sign-in failed with HTTP ${String(response.status)}.`);
    }

    const body = (await response.json()) as Record<string, unknown>;
    const idToken = body["idToken"];
    const refreshToken = body["refreshToken"];
    const expiresIn = body["expiresIn"];

    if (typeof idToken !== "string" || !idToken.trim()) {
      throw new Error("Firebase sign-in did not return an ID token.");
    }

    const parsedSeconds =
      typeof expiresIn === "string" ? Number.parseInt(expiresIn, 10) : Number.NaN;
    const expiresAtMs = Number.isFinite(parsedSeconds)
      ? Date.now() + parsedSeconds * 1000
      : decodeJwtExpiryMs(idToken);

    return {
      idToken,
      refreshToken: typeof refreshToken === "string" ? refreshToken : null,
      expiresAtMs,
    };
  } finally {
    globalThis.clearTimeout(timer);
  }
}

export async function refreshFirebaseIdToken(
  refreshToken: string,
  firebase: FirebaseClientConfigResponse,
): Promise<VerifiedSignInTokens> {
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), AUTH_TIMEOUT_MS);

  try {
    const endpoint = `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(firebase.api_key)}`;
    const bodyParams = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    });
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      signal: controller.signal,
      body: bodyParams.toString(),
    });

    if (!response.ok) {
      throw new Error("Firebase session refresh failed.");
    }

    const body = (await response.json()) as Record<string, unknown>;
    const nextIdToken = body["id_token"];
    const nextRefreshToken = body["refresh_token"];
    const expiresIn = body["expires_in"];

    if (typeof nextIdToken !== "string" || !nextIdToken.trim()) {
      throw new Error("Firebase token refresh response was incomplete.");
    }

    const parsedSeconds =
      typeof expiresIn === "string" ? Number.parseInt(expiresIn, 10) : Number.NaN;
    const expiresAtMs = Number.isFinite(parsedSeconds)
      ? Date.now() + parsedSeconds * 1000
      : decodeJwtExpiryMs(nextIdToken);

    return {
      idToken: nextIdToken,
      refreshToken: typeof nextRefreshToken === "string" ? nextRefreshToken : refreshToken,
      expiresAtMs,
    };
  } finally {
    globalThis.clearTimeout(timer);
  }
}
