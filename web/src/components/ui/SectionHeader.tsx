import type { JSX, ReactNode } from "react";

export interface SectionHeaderProps {
  readonly eyebrow?: string | undefined;
  readonly title: string;
  readonly as?: "h1" | "h2" | "h3" | undefined;
  readonly size?: "page" | "section" | "card" | undefined;
  readonly description?: string | undefined;
  readonly action?: ReactNode | undefined;
  readonly id?: string | undefined;
}

const SIZE_CLASSES: Record<NonNullable<SectionHeaderProps["size"]>, string> = {
  page: "brew-page-heading",
  section: "brew-section-heading",
  card: "brew-card-heading",
};

export function SectionHeader({
  eyebrow,
  title,
  as = "h2",
  size = "section",
  description,
  action,
  id,
}: SectionHeaderProps): JSX.Element {
  const Heading = as;
  return (
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
      <div className="space-y-1">
        {eyebrow && <p className="brew-eyebrow">{eyebrow}</p>}
        <Heading id={id} className={SIZE_CLASSES[size]}>
          {title}
        </Heading>
        {description && <p className="max-w-2xl text-sm text-brew-secondary">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>
  );
}
