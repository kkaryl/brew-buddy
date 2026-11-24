import { Clock, ShieldCheck, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import type { HealthPayload } from "../api/health";
import type { AuthClientConfigResponse } from "../api/types";
import {
  exchangeGoogleCredentialWithFirebase,
  loadGoogleIdentityServicesScript,
  requestGoogleOAuthPopupToken,
  type VerifiedSignInTokens,
} from "../auth/googleFirebaseAuth";
import { decodeJwtExpiryMs } from "../auth/session";
import { errorToFeedbackNotice, type FeedbackNotice } from "./formatters";
import { StatusBanner } from "./StatusFeedback";
import {
  BrewLogo,
  IconTile,
  PastelCard,
  PastelHero,
  PillButton,
  PrimaryButton,
} from "./ui";

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

  const completeGoogleIdCredential = useCallback(
    async (rawCredential: string): Promise<void> => {
      setSubmittingId("google");
      setLocalError(null);
      try {
        let tokens: VerifiedSignInTokens;
        if (authConfig?.firebase) {
          try {
            tokens = await exchangeGoogleCredentialWithFirebase(rawCredential, authConfig.firebase);
          } catch (firebaseErr: unknown) {
            if (!authConfig.google_oauth_client_id) {
              throw firebaseErr;
            }
            tokens = {
              idToken: rawCredential,
              refreshToken: null,
              expiresAtMs: decodeJwtExpiryMs(rawCredential),
            };
          }
        } else {
          tokens = {
            idToken: rawCredential,
            refreshToken: null,
            expiresAtMs: decodeJwtExpiryMs(rawCredential),
          };
        }
        await onVerifiedTokenSignIn(tokens);
      } catch (err: unknown) {
        setLocalError(errorToFeedbackNotice(err, "Google sign-in failed"));
      } finally {
        setSubmittingId(null);
      }
    },
    [authConfig, onVerifiedTokenSignIn],
  );

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
          ux_mode: "popup",
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
            void completeGoogleIdCredential(rawCredential);
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
        setGisButtonRendered(googleBtnContainerRef.current.childElementCount > 0);
      })
      .catch(() => {
        setGisButtonRendered(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authConfig?.google_oauth_client_id, completeGoogleIdCredential, isLoopbackIpOrigin]);

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
      const popupTokens = await requestGoogleOAuthPopupToken(clientId, (rawCredential) => {
        void completeGoogleIdCredential(rawCredential);
      });
      if (popupTokens) {
        await onVerifiedTokenSignIn(popupTokens);
      }
    } catch (err: unknown) {
      setLocalError(errorToFeedbackNotice(err, "Google sign-in failed"));
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
    <div className="min-h-screen bg-brew-bg text-brew-plum">
      <header className="border-b border-brew-border bg-brew-bg/95 backdrop-blur-md md:h-[72px]">
        <div className="mx-auto flex h-full max-w-[1368px] items-center justify-between px-5 py-3.5 md:px-9 md:py-0">
          <BrewLogo size="md" />
        </div>
      </header>

      <main
        id="main-workspace"
        className="mx-auto max-w-[1280px] space-y-8 px-5 py-7 sm:py-10 lg:px-9 lg:py-11"
      >
        <div className="grid items-start gap-7 lg:grid-cols-[1.16fr_0.84fr] lg:gap-9">
          <div className="space-y-6">
            <PastelHero
              eyebrow="AI COFFEE CHAT COMPANION"
              title="Walk into every chat warm, prepared, and human."
              description="Prepare time-boxed cue cards, tailored openers, and grounded questions for coffee chats, mentorship, and discovery, while keeping relationship memory in your hands."
              illustration="chat-setup-hero"
              tone="peach"
              layout="stacked"
            />

            <div className="grid gap-4 sm:grid-cols-3">
              <PastelCard tone="coral" padding="sm" className="space-y-2.5">
                <IconTile icon={Clock} tone="peach" size="sm" />
                <h2 className="font-serif text-base font-bold text-brew-plum">
                  Calendar-Aware Prep
                </h2>
                <p className="text-xs leading-relaxed text-brew-secondary">
                  Realistic 15 to 60 minute cue decks with proportional pacing and Pocket Glance.
                </p>
              </PastelCard>

              <PastelCard tone="lavender" padding="sm" className="space-y-2.5">
                <IconTile icon={Sparkles} tone="lavender" size="sm" />
                <h2 className="font-serif text-base font-bold text-brew-plum">
                  Live Brief Co-Pilot
                </h2>
                <p className="text-xs leading-relaxed text-brew-secondary">
                  Tune tone, length, or focus on the fly with preserved version snapshots.
                </p>
              </PastelCard>

              <PastelCard tone="mint" padding="sm" className="space-y-2.5">
                <IconTile icon={ShieldCheck} tone="mint" size="sm" />
                <h2 className="font-serif text-base font-bold text-brew-plum">
                  Keepsakes You Stamp
                </h2>
                <p className="text-xs leading-relaxed text-brew-secondary">
                  Nothing is remembered silently. Stamp, edit, or toss every takeaway first.
                </p>
              </PastelCard>
            </div>
          </div>

          <PastelCard
            as="section"
            tone="paper"
            padding="lg"
            ariaLabelledBy="sign-in-card-heading"
            className="space-y-6 lg:sticky lg:top-24"
          >
            <div className="space-y-1">
              <p className="brew-eyebrow">WELCOME IN</p>
              <h2 id="sign-in-card-heading" className="brew-section-heading">
                Sign in to your workspace
              </h2>
              <p className="text-sm leading-relaxed text-brew-secondary">
                Folios, cue decks, and relationship keepsakes stay private to your verified
                account.
              </p>
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
                  className="space-y-3 rounded-2xl border border-[#EFE0A8] bg-brew-yellow p-4 text-xs text-brew-plum"
                >
                  <p className="font-bold">
                    Google Sign-In requires <code className="font-mono-code">localhost</code> instead
                    of <code className="font-mono-code">127.0.0.1</code>
                  </p>
                  <p className="text-brew-secondary">
                    Google OAuth blocks <code className="font-mono-code">127.0.0.1</code> with{" "}
                    <code className="font-mono-code">origin_mismatch</code>. Switch this tab to{" "}
                    <code className="font-mono-code">{localhostEquivalentUrl}</code>.
                  </p>
                  <a
                    id="link-switch-to-localhost"
                    href={localhostEquivalentUrl}
                    className="inline-flex min-h-[44px] w-full items-center justify-center rounded-full bg-brew-dark-btn px-4 py-2 text-xs font-semibold text-white"
                  >
                    Switch to {localhostEquivalentUrl}
                  </a>
                </div>
              )}

              {authConfig?.google_oauth_client_id && !isLoopbackIpOrigin ? (
                <div
                  ref={googleBtnContainerRef}
                  className={
                    gisButtonRendered
                      ? "flex min-h-[46px] items-center justify-center"
                      : "h-0 overflow-hidden"
                  }
                />
              ) : null}

              {!gisButtonRendered && !(authConfig?.google_oauth_client_id && isLoopbackIpOrigin) && (
                <PrimaryButton
                  id="btn-google-sign-in"
                  fullWidth
                  shape="pill"
                  loading={submittingId === "google"}
                  disabled={submittingId !== null || health.kind === "loading"}
                  onClick={() => {
                    void handleManualGooglePrompt();
                  }}
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
                </PrimaryButton>
              )}

              {gisButtonRendered && authConfig?.google_oauth_client_id && !isLoopbackIpOrigin && (
                <div className="text-center">
                  <button
                    id="btn-google-popup-fallback"
                    type="button"
                    disabled={submittingId !== null}
                    onClick={() => {
                      void handleManualGooglePrompt();
                    }}
                    className="cursor-pointer text-xs font-semibold text-brew-secondary underline hover:text-brew-plum disabled:opacity-50"
                  >
                    {submittingId === "google"
                      ? "Opening Google Sign-In..."
                      : "Embedded button blocked? Sign in via Google popup"}
                  </button>
                </div>
              )}
            </div>

            {authConfig?.local_mock_enabled && authConfig.mock_personas.length > 0 && (
              <div className="space-y-3 border-t border-brew-border pt-5">
                <span className="brew-eyebrow">Local Workspace Personas</span>

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
                      className="flex min-h-[56px] w-full cursor-pointer items-center justify-between gap-3 rounded-2xl border border-brew-border bg-brew-blush/55 px-4 py-3 text-left transition hover:border-brew-coral hover:bg-brew-peach/65 disabled:opacity-50"
                    >
                      <span className="flex flex-col items-start">
                        <span className="text-sm font-bold text-brew-plum">
                          Continue as {persona.display_name}
                        </span>
                        <span className="text-xs text-brew-secondary">{persona.role_summary}</span>
                      </span>
                      <span className="rounded-full bg-brew-paper px-3 py-1 text-xs font-bold text-brew-plum shadow-xs">
                        {submittingId === persona.persona_id ? "Opening..." : "Enter"}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {health.kind === "error" && (
              <div className="flex justify-end border-t border-brew-border pt-3">
                <PillButton
                  id="btn-refresh-runtime-status"
                  variant="ghost"
                  size="sm"
                  onClick={onRefreshStatus}
                >
                  Retry Connection
                </PillButton>
              </div>
            )}
          </PastelCard>
        </div>
      </main>
    </div>
  );
}
