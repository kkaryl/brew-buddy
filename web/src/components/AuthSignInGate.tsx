import { useEffect, useRef, useState, type JSX } from "react";
import type { HealthPayload } from "../api/health";
import type { AuthClientConfigResponse } from "../api/types";
import {
  exchangeGoogleCredentialWithFirebase,
  loadGoogleIdentityServicesScript,
  type VerifiedSignInTokens,
} from "../auth/googleFirebaseAuth";
import { decodeJwtExpiryMs } from "../auth/session";
import { errorToFeedbackNotice, type FeedbackNotice } from "./formatters";
import { StatusBanner } from "./StatusFeedback";

export interface AuthSignInGateProps {
  readonly health:
    | { readonly kind: "loading" }
    | { readonly kind: "ready"; readonly data: HealthPayload }
    | { readonly kind: "error"; readonly message: string };
  readonly authConfig: AuthClientConfigResponse | null;
  readonly authConfigError: string | null;
  readonly sessionExpiredReason: string | null;
  readonly onRefreshStatus: () => void;
  readonly onVerifiedTokenSignIn: (tokens: VerifiedSignInTokens) => Promise<void>;
  readonly onLocalMockSignIn: (personaId: string) => Promise<void>;
}

export function AuthSignInGate({
  health,
  authConfig,
  authConfigError,
  sessionExpiredReason,
  onRefreshStatus,
  onVerifiedTokenSignIn,
  onLocalMockSignIn,
}: AuthSignInGateProps): JSX.Element {
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [localError, setLocalError] = useState<FeedbackNotice | null>(null);
  const [gisButtonRendered, setGisButtonRendered] = useState(false);
  const googleBtnContainerRef = useRef<HTMLDivElement | null>(null);

  const isLoopbackIpOrigin =
    typeof window !== "undefined" && window.location.hostname === "127.0.0.1";
  const localhostEquivalentUrl =
    typeof window !== "undefined"
      ? `${window.location.protocol}//localhost${window.location.port ? `:${window.location.port}` : ""}${window.location.pathname}${window.location.search}`
      : "http://localhost:5173";

  useEffect(() => {
    const clientId = authConfig?.google_oauth_client_id;
    const container = googleBtnContainerRef.current;
    if (!clientId || !container || isLoopbackIpOrigin) {
      setGisButtonRendered(false);
      return;
    }
    let cancelled = false;
    void loadGoogleIdentityServicesScript()
      .then(() => {
        if (cancelled || !window.google?.accounts?.id || !googleBtnContainerRef.current) {
          return;
        }
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (resp) => {
            const rawCredential = resp.credential;
            if (!rawCredential) {
              setLocalError({
                kind: "error",
                title: "Google sign-in was cancelled",
                message: "No identity credential was returned by Google.",
              });
              return;
            }
            setSubmittingId("google");
            setLocalError(null);
            const completePromise = authConfig.firebase
              ? exchangeGoogleCredentialWithFirebase(rawCredential, authConfig.firebase)
              : Promise.resolve<VerifiedSignInTokens>({
                  idToken: rawCredential,
                  refreshToken: null,
                  expiresAtMs: decodeJwtExpiryMs(rawCredential),
                });
            void completePromise
              .then((tokens) => onVerifiedTokenSignIn(tokens))
              .catch((err: unknown) => {
                setLocalError(errorToFeedbackNotice(err, "Google sign-in failed"));
              })
              .finally(() => {
                setSubmittingId(null);
              });
          },
        });
        googleBtnContainerRef.current.innerHTML = "";
        window.google.accounts.id.renderButton(googleBtnContainerRef.current, {
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "pill",
          width: 340,
        });
        setGisButtonRendered(true);
      })
      .catch(() => {
        setGisButtonRendered(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authConfig, isLoopbackIpOrigin, onVerifiedTokenSignIn]);

  const handleManualGooglePrompt = async (): Promise<void> => {
    const clientId = authConfig?.google_oauth_client_id;
    if (!clientId) {
      setLocalError({
        kind: "info",
        title: "Google Sign-In requires OAuth client configuration",
        message:
          "Configure GOOGLE_OAUTH_CLIENT_ID (and optional FIREBASE_PROJECT_ID / FIREBASE_WEB_API_KEY) on the backend to enable browser Google Sign-In.",
      });
      return;
    }
    if (isLoopbackIpOrigin) {
      window.location.assign(localhostEquivalentUrl);
      return;
    }
    setLocalError(null);
    setSubmittingId("google");
    try {
      await loadGoogleIdentityServicesScript();
      window.google?.accounts?.id?.prompt();
    } catch (err: unknown) {
      setLocalError(errorToFeedbackNotice(err, "Unable to open Google Sign-In"));
    } finally {
      setSubmittingId(null);
    }
  };

  const handleMockPersonaClick = async (personaId: string): Promise<void> => {
    setLocalError(null);
    setSubmittingId(personaId);
    try {
      await onLocalMockSignIn(personaId);
    } catch (err: unknown) {
      setLocalError(errorToFeedbackNotice(err, "Sign-in failed"));
    } finally {
      setSubmittingId(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#FAF6F0] px-4 py-10 sm:px-6 lg:py-16">
      <main
        id="main-workspace"
        className="mx-auto grid max-w-5xl gap-8 lg:grid-cols-[1.1fr_0.95fr] lg:items-center"
      >
        <section className="space-y-6">
          <div className="inline-flex items-center gap-2.5 rounded-full border border-[#D6C7B7] bg-[#F5EEE4] px-3.5 py-1.5 text-xs font-semibold text-[#4A2E1B]">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[#4A2E1B]" />
            <span>Coffee Chat &amp; Relationship Preparation</span>
          </div>

          <h1 className="font-display text-4xl font-semibold tracking-tight text-[#23170F] sm:text-5xl">
            Brew
          </h1>

          <p className="max-w-xl text-base leading-relaxed text-[#594638] sm:text-lg">
            Walk into every coffee chat, mentorship session, and customer discovery conversation
            with a time-boxed agenda, grounded questions, and relationship context you explicitly
            approve.
          </p>

          <dl className="grid gap-4 pt-2 sm:grid-cols-3">
            <div className="md-card-tonal p-4">
              <dt className="text-xs font-semibold text-[#4A2E1B]">Time-Boxed Agendas</dt>
              <dd className="mt-1 text-xs leading-relaxed text-[#594638]">
                Tailored openers and realistic minute-by-minute pacing for 15 to 60 minute chats.
              </dd>
            </div>
            <div className="md-card-tonal p-4">
              <dt className="text-xs font-semibold text-[#4A2E1B]">Iterative Refinement</dt>
              <dd className="mt-1 text-xs leading-relaxed text-[#594638]">
                Adjust duration, tone, or focus in natural language with full revision history.
              </dd>
            </div>
            <div className="md-card-tonal p-4">
              <dt className="text-xs font-semibold text-[#4A2E1B]">Consented Memory</dt>
              <dd className="mt-1 text-xs leading-relaxed text-[#594638]">
                Review, edit, or reject post-meeting takeaways before anything is remembered.
              </dd>
            </div>
          </dl>
        </section>

        <section
          aria-labelledby="sign-in-card-heading"
          className="md-card-elevated space-y-6 p-6 sm:p-8"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="sign-in-card-heading" className="text-xl font-semibold text-[#23170F]">
                Sign in to your workspace
              </h2>
              <p className="mt-1 text-sm text-[#594638]">
                Contacts, preparation briefs, and memories are isolated to your verified account.
              </p>
            </div>
            <RuntimeStatusPill health={health} />
          </div>

          {sessionExpiredReason && (
            <StatusBanner
              notice={{
                kind: "error",
                title: "Session expired",
                message: sessionExpiredReason,
              }}
            />
          )}

          {health.kind === "error" && (
            <StatusBanner
              notice={{
                kind: "error",
                title: "Backend connection unavailable",
                message: health.message,
              }}
            />
          )}

          {authConfigError && health.kind !== "error" && (
            <StatusBanner
              notice={{
                kind: "error",
                title: "Authentication service unavailable",
                message: authConfigError,
              }}
            />
          )}

          {localError && (
            <StatusBanner
              notice={localError}
              onDismiss={() => {
                setLocalError(null);
              }}
            />
          )}

          <div className="space-y-3">
            {authConfig?.google_oauth_client_id && isLoopbackIpOrigin && (
              <div
                role="alert"
                className="space-y-2.5 rounded-2xl border border-[#E5CFA4] bg-[#F8E8CB] p-4 text-xs text-[#3F2702]"
              >
                <p className="font-semibold">
                  Google Sign-In requires <code className="font-mono-code">localhost</code> instead of{" "}
                  <code className="font-mono-code">127.0.0.1</code>
                </p>
                <p>
                  Google OAuth blocks <code className="font-mono-code">127.0.0.1</code> with{" "}
                  <code className="font-mono-code">origin_mismatch</code>. Switch this tab to{" "}
                  <code className="font-mono-code">{localhostEquivalentUrl}</code>.
                </p>
                <a
                  id="link-switch-to-localhost"
                  href={localhostEquivalentUrl}
                  className="md-btn md-btn-filled w-full text-xs"
                >
                  Switch to {localhostEquivalentUrl}
                </a>
              </div>
            )}

            {authConfig?.google_oauth_client_id && !isLoopbackIpOrigin ? (
              <div
                ref={googleBtnContainerRef}
                className={
                  gisButtonRendered ? "flex min-h-[44px] items-center justify-center" : "hidden"
                }
              />
            ) : null}

            {!gisButtonRendered && !(authConfig?.google_oauth_client_id && isLoopbackIpOrigin) && (
              <button
                id="btn-google-sign-in"
                type="button"
                onClick={() => {
                  void handleManualGooglePrompt();
                }}
                disabled={submittingId !== null || health.kind === "loading"}
                className="md-btn md-btn-filled w-full"
              >
                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24"
                  className="h-4 w-4 shrink-0 fill-current"
                >
                  <path d="M21.35 11.1H12v2.92h5.35c-.24 1.38-1.02 2.55-2.18 3.33v2.76h3.52c2.06-1.9 3.25-4.7 3.25-8.04 0-.65-.06-1.31-.19-1.97Z" />
                  <path d="M12 22c2.97 0 5.46-.98 7.28-2.66l-3.52-2.76c-.98.66-2.24 1.06-3.76 1.06-2.89 0-5.34-1.95-6.21-4.58H2.15v2.85A10.99 10.99 0 0 0 12 22Z" />
                  <path d="M5.79 13.06A6.62 6.62 0 0 1 5.44 11c0-.72.13-1.41.35-2.06V6.09H2.15A10.99 10.99 0 0 0 1 11c0 1.77.43 3.45 1.15 4.91l3.64-2.85Z" />
                  <path d="M12 4.38c1.62 0 3.07.56 4.22 1.65l3.16-3.16C17.45 1.09 14.97 0 12 0 7.7 0 3.99 2.47 2.15 6.09l3.64 2.85C6.66 6.33 9.11 4.38 12 4.38Z" />
                </svg>
                <span>
                  {submittingId === "google" ? "Signing in with Google..." : "Continue with Google"}
                </span>
              </button>
            )}
          </div>

          {authConfig?.local_mock_enabled && authConfig.mock_personas.length > 0 && (
            <div className="space-y-3 border-t border-[#D6C7B7] pt-5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold tracking-wide text-[#594638] uppercase">
                  Local Isolated Test Mode
                </span>
                <span className="md-badge md-badge-amber">Disabled in deployment</span>
              </div>

              <div className="grid gap-2.5">
                {authConfig.mock_personas.map((persona) => (
                  <button
                    key={persona.persona_id}
                    id={`btn-mock-persona-${persona.persona_id}`}
                    type="button"
                    disabled={submittingId !== null}
                    onClick={() => {
                      void handleMockPersonaClick(persona.persona_id);
                    }}
                    className="md-btn md-btn-outlined w-full justify-between px-4 py-2.5 text-left"
                  >
                    <span className="flex flex-col items-start">
                      <span className="text-sm font-semibold text-[#23170F]">
                        Continue as {persona.display_name}
                      </span>
                      <span className="text-xs font-normal text-[#594638]">
                        {persona.role_summary}
                      </span>
                    </span>
                    <span className="text-xs font-semibold text-[#4A2E1B]">
                      {submittingId === persona.persona_id ? "Opening..." : "Enter"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between border-t border-[#E6DACB] pt-4 text-xs text-[#594638]">
            <div>
              {health.kind === "ready" ? (
                <span className="font-mono-code">
                  {health.data.service} v{health.data.version} · {health.data.model}
                </span>
              ) : (
                <span>Runtime status check</span>
              )}
            </div>
            <button
              id="btn-refresh-runtime-status"
              type="button"
              onClick={onRefreshStatus}
              disabled={health.kind === "loading"}
              className="md-btn md-btn-text min-h-8 px-3 py-1 text-xs"
            >
              Refresh Status
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}

function RuntimeStatusPill({
  health,
}: {
  readonly health: AuthSignInGateProps["health"];
}): JSX.Element {
  if (health.kind === "loading") {
    return (
      <span className="md-badge md-badge-neutral" role="status">
        Checking
      </span>
    );
  }
  if (health.kind === "error") {
    return <span className="md-badge md-badge-error">Offline</span>;
  }
  return (
    <span className="md-badge md-badge-sage">
      Backend {health.data.status.toUpperCase()}
    </span>
  );
}
