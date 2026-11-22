import { useCallback, useEffect, useState, type JSX } from "react";
import { fetchBackendHealth, type HealthPayload } from "./api/health";

type ViewState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly data: HealthPayload }
  | { readonly kind: "error"; readonly message: string };

export function App(): JSX.Element {
  const [state, setState] = useState<ViewState>({ kind: "loading" });

  const runHealthCheck = useCallback(async (): Promise<void> => {
    setState({ kind: "loading" });
    try {
      const payload = await fetchBackendHealth();
      setState({ kind: "ready", data: payload });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Unexpected backend health error.";
      setState({ kind: "error", message });
    }
  }, []);

  useEffect(() => {
    void runHealthCheck();
  }, [runHealthCheck]);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-6 py-16">
      <section className="rounded-2xl border border-stone-800 bg-stone-900/80 p-8 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold tracking-widest text-amber-400 uppercase">
              Project Foundation
            </p>
            <h1 className="mt-1 text-3xl font-bold tracking-tight text-stone-50">
              Brew
            </h1>
            <p className="mt-2 text-sm text-stone-400">
              AI-powered Coffee Chat Buddy — runtime readiness monitor.
            </p>
          </div>

          <StatusBadge state={state} />
        </div>

        <div className="mt-8 rounded-xl border border-stone-800 bg-stone-950/70 p-5">
          {state.kind === "loading" && (
            <p className="text-sm text-stone-400" role="status">
              Checking backend health...
            </p>
          )}

          {state.kind === "error" && (
            <div role="alert" className="space-y-1">
              <p className="text-sm font-medium text-rose-400">
                Backend connection unavailable
              </p>
              <p className="text-xs text-stone-400">{state.message}</p>
            </div>
          )}

          {state.kind === "ready" && (
            <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs text-stone-500">Service</dt>
                <dd className="mt-0.5 font-mono text-stone-200">
                  {state.data.service} v{state.data.version}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-stone-500">Environment</dt>
                <dd className="mt-0.5 font-mono text-stone-200">
                  {state.data.environment}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-stone-500">Configured Gemini Model</dt>
                <dd className="mt-0.5 font-mono text-amber-300">
                  {state.data.model}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-stone-500">Checked (UTC)</dt>
                <dd className="mt-0.5 font-mono text-xs text-stone-300">
                  {state.data.timestamp_utc}
                </dd>
              </div>
            </dl>
          )}
        </div>

        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={() => {
              void runHealthCheck();
            }}
            disabled={state.kind === "loading"}
            className="rounded-lg border border-stone-700 bg-stone-800 px-4 py-2 text-xs font-medium text-stone-100 transition hover:border-amber-500/60 hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Refresh Status
          </button>
        </div>
      </section>
    </main>
  );
}

function StatusBadge({ state }: { readonly state: ViewState }): JSX.Element {
  if (state.kind === "loading") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-stone-700 bg-stone-800 px-3 py-1 text-xs font-medium text-stone-300">
        <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
        Checking
      </span>
    );
  }

  if (state.kind === "error") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-rose-900 bg-rose-950/70 px-3 py-1 text-xs font-medium text-rose-300">
        <span className="h-2 w-2 rounded-full bg-rose-400" />
        Offline
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-emerald-900 bg-emerald-950/70 px-3 py-1 text-xs font-medium text-emerald-300">
      <span className="h-2 w-2 rounded-full bg-emerald-400" />
      Backend {state.data.status.toUpperCase()}
    </span>
  );
}
