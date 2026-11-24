import type { JSX } from "react";
import { Illustration, type IllustrationName } from "./Illustration";
import { PastelCard, type PastelCardTone } from "./PastelCard";
import { PrimaryButton } from "./PrimaryButton";

export interface EmptyStateProps {
  readonly title: string;
  readonly description: string;
  readonly illustration?: IllustrationName | undefined;
  readonly tone?: PastelCardTone | undefined;
  readonly actionLabel?: string | undefined;
  readonly actionId?: string | undefined;
  readonly onAction?: (() => void) | undefined;
}

export function EmptyState({
  title,
  description,
  illustration,
  tone = "paper",
  actionLabel,
  actionId,
  onAction,
}: EmptyStateProps): JSX.Element {
  return (
    <PastelCard
      tone={tone}
      padding="lg"
      className="flex flex-col items-center justify-between gap-6 text-center sm:flex-row sm:text-left"
    >
      <div className="space-y-2.5">
        <h3 className="brew-card-heading">{title}</h3>
        <p className="max-w-xl text-sm leading-relaxed text-brew-secondary">{description}</p>
        {actionLabel && onAction && (
          <div className="pt-2">
            <PrimaryButton id={actionId} onClick={onAction}>
              {actionLabel}
            </PrimaryButton>
          </div>
        )}
      </div>

      {illustration && (
        <Illustration
          name={illustration}
          decorative
          className="h-36 w-48 shrink-0 sm:h-40 sm:w-52"
        />
      )}
    </PastelCard>
  );
}
