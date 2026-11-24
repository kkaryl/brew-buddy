import type { JSX } from "react";

export interface BrewLogoProps {
  readonly size?: "sm" | "md" | "lg" | undefined;
  readonly onClick?: (() => void) | undefined;
  readonly id?: string | undefined;
}

const SIZE_CLASSES: Record<NonNullable<BrewLogoProps["size"]>, string> = {
  sm: "text-[24px]",
  md: "text-[32px]",
  lg: "text-[40px]",
};

export function BrewLogo({ size = "md", onClick, id }: BrewLogoProps): JSX.Element {
  const wordmark = (
    <span className={`brew-wordmark inline-flex items-baseline select-none ${SIZE_CLASSES[size]}`}>
      <span>brew</span>
      <span className="text-brew-coral" aria-hidden="true">
        .
      </span>
    </span>
  );

  if (onClick) {
    return (
      <button
        id={id}
        type="button"
        onClick={onClick}
        aria-label="brew. home"
        className="inline-flex min-h-[44px] items-center rounded-2xl px-1.5 py-1 transition hover:opacity-85"
      >
        {wordmark}
      </button>
    );
  }

  return wordmark;
}
