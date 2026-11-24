import type { JSX } from "react";
import type { FeedbackNotice } from "./formatters";
import { EmptyState, LoadingSkeleton, PillButton, type IllustrationName } from "./ui";

export function StatusBanner({
  notice,
  onDismiss,
}: {
  readonly notice: FeedbackNotice;
  readonly onDismiss?: (() => void) | undefined;
}): JSX.Element {
  const isError = notice.kind === "error";
  const containerStyles =
    notice.kind === "error"
      ? "border-[#F3C1B8] bg-[#FFF1EE] text-[#7D2418]"
      : notice.kind === "success"
        ? "border-[#C4E6D3] bg-[#F0F8F3] text-[#1F543F]"
        : "border-[#DFD4F8] bg-[#F5F0FC] text-[#302731]";

  return (
    <div
      role={isError ? "alert" : "status"}
      aria-live={isError ? "assertive" : "polite"}
      className={`rounded-[22px] border px-5 py-4 text-sm shadow-card ${containerStyles}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="font-bold">{notice.title}</p>
          {notice.message && <p className="text-[0.875rem] opacity-95">{notice.message}</p>}
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
            <p className="pt-0.5 font-mono-code text-[0.72rem]">
              Trace: {notice.traceId}
            </p>
          )}
        </div>
        {onDismiss && (
          <PillButton
            variant="ghost"
            size="sm"
            onClick={onDismiss}
            aria-label="Dismiss notification"
          >
            Dismiss
          </PillButton>
        )}
      </div>
    </div>
  );
}

export function LoadingCard({ label }: { readonly label: string }): JSX.Element {
  return <LoadingSkeleton label={label} rows={3} />;
}

export function EmptyStateCard({
  title,
  description,
  actionLabel,
  onAction,
  actionId,
  illustration,
}: {
  readonly title: string;
  readonly description: string;
  readonly actionLabel?: string | undefined;
  readonly onAction?: (() => void) | undefined;
  readonly actionId?: string | undefined;
  readonly illustration?: IllustrationName | undefined;
}): JSX.Element {
  return (
    <EmptyState
      title={title}
      description={description}
      actionLabel={actionLabel}
      onAction={onAction}
      actionId={actionId}
      illustration={illustration}
    />
  );
}
