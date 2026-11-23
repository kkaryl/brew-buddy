import type { JSX } from "react";
import type { FeedbackNotice } from "./formatters";

export function StatusBanner({
  notice,
  onDismiss,
}: {
  readonly notice: FeedbackNotice;
  readonly onDismiss?: () => void;
}): JSX.Element {
  const isError = notice.kind === "error";
  const containerStyles =
    notice.kind === "error"
      ? "border-[#E6B8B7] bg-[#FCEAE9] text-[#5A1213]"
      : notice.kind === "success"
        ? "border-[#B8D4C0] bg-[#DCEADF] text-[#133321]"
        : "border-[#D6C7B7] bg-[#F5EEE4] text-[#2B170A]";

  return (
    <div
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      className={`rounded-2xl border px-4 py-3.5 text-sm ${containerStyles}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="font-semibold">{notice.title}</p>
          {notice.message && <p className="text-[0.84rem] opacity-95">{notice.message}</p>}
          {notice.details && notice.details.length > 0 && (
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-xs">
              {notice.details.map((detail, idx) => (
                <li key={`${detail.field}-${String(idx)}`}>
                  <span className="font-mono-code font-medium">{detail.field}</span>:{" "}
                  {detail.message}
                </li>
              ))}
            </ul>
          )}
          {notice.traceId && (
            <p className="pt-0.5 font-mono-code text-[0.72rem] opacity-80">
              Trace: {notice.traceId}
            </p>
          )}
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss notification"
            className="rounded-full px-2.5 py-1 text-xs font-semibold opacity-80 transition hover:bg-black/5 hover:opacity-100"
          >
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
}

export function LoadingCard({ label }: { readonly label: string }): JSX.Element {
  return (
    <div
      role="status"
      aria-live="polite"
      className="md-card flex items-center gap-3.5 px-6 py-5 text-sm text-[#594638]"
    >
      <span
        aria-hidden="true"
        className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-[#D6C7B7] border-t-[#4A2E1B]"
      />
      <span className="font-medium">{label}</span>
    </div>
  );
}

export function EmptyStateCard({
  title,
  description,
  actionLabel,
  onAction,
  actionId,
}: {
  readonly title: string;
  readonly description: string;
  readonly actionLabel?: string;
  readonly onAction?: () => void;
  readonly actionId?: string;
}): JSX.Element {
  return (
    <div className="md-card-tonal flex flex-col items-start justify-between gap-4 p-6 sm:flex-row sm:items-center">
      <div className="space-y-1">
        <h3 className="text-base font-semibold text-[#23170F]">{title}</h3>
        <p className="max-w-xl text-sm text-[#594638]">{description}</p>
      </div>
      {actionLabel && onAction && (
        <button
          id={actionId}
          type="button"
          onClick={onAction}
          className="md-btn md-btn-filled shrink-0"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
