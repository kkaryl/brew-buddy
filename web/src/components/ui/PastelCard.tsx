import type { JSX, ReactNode } from "react";

export type PastelCardTone =
  | "paper"
  | "lavender"
  | "mint"
  | "coral"
  | "blush"
  | "yellow";

export interface PastelCardProps {
  readonly children: ReactNode;
  readonly tone?: PastelCardTone | undefined;
  readonly as?: "div" | "section" | "article" | "li" | undefined;
  readonly padding?: "sm" | "md" | "lg" | undefined;
  readonly className?: string | undefined;
  readonly ariaLabelledBy?: string | undefined;
  readonly id?: string | undefined;
}

const TONE_CLASSES: Record<PastelCardTone, string> = {
  paper: "brew-card-paper",
  lavender: "brew-card-lavender",
  mint: "brew-card-mint",
  coral: "brew-card-coral",
  blush: "brew-card-blush",
  yellow: "brew-card-yellow",
};

const PADDING_CLASSES: Record<NonNullable<PastelCardProps["padding"]>, string> = {
  sm: "p-5",
  md: "p-6",
  lg: "p-6 sm:p-7",
};

export function PastelCard({
  children,
  tone = "paper",
  as = "div",
  padding = "md",
  className = "",
  ariaLabelledBy,
  id,
}: PastelCardProps): JSX.Element {
  const Component = as;
  return (
    <Component
      id={id}
      aria-labelledby={ariaLabelledBy}
      className={`rounded-card ${TONE_CLASSES[tone]} ${PADDING_CLASSES[padding]} ${className}`}
    >
      {children}
    </Component>
  );
}
