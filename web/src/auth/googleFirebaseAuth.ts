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

interface GooglePromptNotification {
  isNotDisplayed: () => boolean;
  isSkippedMoment: () => boolean;
  getNotDisplayedReason?: () => string;
  getSkippedReason?: () => string;
}

interface GoogleAccountsIdApi {
  initialize: (config: {
    client_id: string;
    callback: (response: GoogleCredentialResponse) => void;
    auto_select?: boolean;
    cancel_on_tap_outside?: boolean;
    ux_mode?: "popup" | "redirect";
  }) => void;
  prompt: (momentListener?: (notification: GooglePromptNotification) => void) => void;
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

interface GoogleOAuthTokenResponse {
  readonly access_token?: string;
  readonly expires_in?: number | string;
  readonly error?: string;
  readonly error_description?: string;
}

interface GoogleOAuthErrorResponse {
  readonly type?: string;
  readonly message?: string;
}

interface GoogleOAuthTokenClient {
  requestAccessToken: (overrideConfig?: { readonly prompt?: string }) => void;
}

interface GoogleAccountsOAuth2Api {
  initTokenClient: (config: {
    client_id: string;
    scope: string;
    prompt?: string;
    callback: (response: GoogleOAuthTokenResponse) => void;
    error_callback?: (error: GoogleOAuthErrorResponse) => void;
  }) => GoogleOAuthTokenClient;
}

declare global {
  interface Window {
    google?: {
      accounts?: {
        id?: GoogleAccountsIdApi;
        oauth2?: GoogleAccountsOAuth2Api;
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
  if (window.google?.accounts?.id || window.google?.accounts?.oauth2) {
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
      existing.remove();
    }

    const script = document.createElement("script");
    script.src = GIS_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => {
      gisScriptPromise = null;
      reject(
        new Error(
          "Unable to load Google Identity Services (accounts.google.com). Check your network or content-blocker settings.",
        ),
      );
    };
    document.head.appendChild(script);
  });

  return gisScriptPromise;
}

/**
 * Launch an interactive Google OAuth 2.0 popup chooser for ``clientId`` and return a verified
 * token payload. Unlike Google One Tap (`id.prompt`), this opens a first-party Google popup
 * directly from a user click gesture and never silently suppresses on FedCM cooldowns.
 */
export async function requestGoogleOAuthPopupToken(
  clientId: string,
  onIdTokenFallback?: (credential: string) => void,
): Promise<VerifiedSignInTokens | null> {
  await loadGoogleIdentityServicesScript();

  const oauth2 = window.google?.accounts?.oauth2;
  if (oauth2?.initTokenClient) {
    return new Promise<VerifiedSignInTokens>((resolve, reject) => {
      const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:5173";
      const tokenClient = oauth2.initTokenClient({
        client_id: clientId,
        scope: "openid email profile",
        prompt: "select_account",
        callback: (resp) => {
          if (resp.error) {
            if (resp.error === "origin_mismatch" || resp.error === "redirect_uri_mismatch") {
              reject(
                new Error(
                  `Google OAuth rejected origin ${origin} (${resp.error}). Add ${origin} under Authorized JavaScript origins for your OAuth 2.0 Web Client in Google Cloud Console.`,
                ),
              );
              return;
            }
            reject(
              new Error(
                resp.error_description
                  ? `Google sign-in failed: ${resp.error_description}`
                  : `Google sign-in failed (${resp.error}).`,
              ),
            );
            return;
          }
          const accessToken = resp.access_token?.trim();
          if (!accessToken) {
            reject(new Error("Google sign-in completed without returning an access token."));
            return;
          }
          const rawExpires =
            typeof resp.expires_in === "number"
              ? resp.expires_in
              : typeof resp.expires_in === "string"
                ? Number.parseInt(resp.expires_in, 10)
                : Number.NaN;
          const expiresAtMs = Number.isFinite(rawExpires)
            ? Date.now() + rawExpires * 1000
            : Date.now() + 3600 * 1000;
          resolve({
            idToken: accessToken,
            refreshToken: null,
            expiresAtMs,
          });
        },
        error_callback: (err) => {
          if (err.type === "popup_closed") {
            reject(new Error("Google sign-in popup was closed before completing sign-in."));
            return;
          }
          if (err.type === "popup_failed_to_open") {
            reject(
              new Error(
                "Browser blocked the Google sign-in popup. Allow popups for this site and try again.",
              ),
            );
            return;
          }
          reject(
            new Error(
              err.message ??
                `Google sign-in could not start (${err.type ?? "unknown_error"}). Ensure ${origin} is listed in Authorized JavaScript origins in Google Cloud Console.`,
            ),
          );
        },
      });
      tokenClient.requestAccessToken({ prompt: "select_account" });
    });
  }

  // Fallback for test environments where only google.accounts.id is stubbed
  const idApi = window.google?.accounts?.id;
  if (idApi) {
    if (onIdTokenFallback) {
      idApi.initialize({
        client_id: clientId,
        ux_mode: "popup",
        callback: (resp) => {
          if (resp.credential) {
            onIdTokenFallback(resp.credential);
          }
        },
      });
    }
    return new Promise<null>((resolve, reject) => {
      let settled = false;
      const timer = globalThis.setTimeout(() => {
        if (!settled) {
          settled = true;
          resolve(null);
        }
      }, 600);
      idApi.prompt((notification) => {
        if (settled) {
          return;
        }
        if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
          settled = true;
          globalThis.clearTimeout(timer);
          const reason =
            notification.getNotDisplayedReason?.() ??
            notification.getSkippedReason?.() ??
            "suppressed";
          const origin =
            typeof window !== "undefined" ? window.location.origin : "http://localhost:5173";
          reject(
            new Error(
              `Google One Tap could not display (${reason}). Confirm ${origin} is added under Authorized JavaScript origins in Google Cloud Console.`,
            ),
          );
        }
      });
    });
  }

  throw new Error("Google Identity Services SDK did not initialize in this browser.");
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
