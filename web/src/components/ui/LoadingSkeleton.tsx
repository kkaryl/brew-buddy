import type { JSX } from "react";
import { PastelCard } from "./PastelCard";

export interface LoadingSkeletonProps {
  readonly label?: string | undefined;
  readonly rows?: number | undefined;
}

export function LoadingSkeleton({
  label = "Loading workspace...",
  rows = 3,
}: LoadingSkeletonProps): JSX.Element {
  return (
    <PastelCard tone="paper" padding="lg">
      <div role="status" aria-live="polite" className="space-y-4">
        <div className="flex items-center gap-3">
          <span
            aria-hidden="true"
            className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-brew-peach border-t-brew-coral-vibrant"
          />
          <span className="text-sm font-semibold text-brew-secondary">{label}</span>
        </div>

        <div aria-hidden="true" className="space-y-3 pt-1">
          {Array.from({ length: rows }).map((_, index) => (
            <div
              key={`skeleton-row-${String(index)}`}
              className={`h-4 animate-pulse rounded-full bg-brew-blush ${
                index === rows - 1 ? "w-2/3" : "w-full"
              }`}
            />
          ))}
        </div>
      </div>
    </PastelCard>
  );
}
