import type { JSX, ReactNode } from "react";
import { Illustration, type IllustrationName } from "./Illustration";

export type PastelHeroTone = "peach" | "lavender" | "mint" | "coral";

export interface PastelHeroProps {
  readonly eyebrow?: string | undefined;
  readonly title: string;
  readonly headingLevel?: "h1" | "h2" | undefined;
  readonly description?: string | undefined;
  readonly illustration: IllustrationName;
  readonly illustrationAlt?: string | undefined;
  readonly tone?: PastelHeroTone | undefined;
  readonly layout?: "split" | "stacked" | undefined;
  readonly actions?: ReactNode | undefined;
  readonly children?: ReactNode | undefined;
  readonly className?: string | undefined;
}

const TONE_CLASSES: Record<PastelHeroTone, string> = {
  peach: "brew-hero-peach",
  lavender: "brew-card-lavender",
  mint: "brew-card-mint",
  coral: "brew-card-coral",
};

export function PastelHero({
  eyebrow,
  title,
  headingLevel = "h1",
  description,
  illustration,
  illustrationAlt,
  tone = "peach",
  layout = "split",
  actions,
  children,
  className = "",
}: PastelHeroProps): JSX.Element {
  const HeadingTag = headingLevel;
  const isStacked = layout === "stacked";

  return (
    <section
      className={`rounded-hero overflow-hidden p-6 sm:p-8 lg:p-9 ${TONE_CLASSES[tone]} ${className}`}
    >
      <div
        className={
          isStacked
            ? "flex flex-col gap-6"
            : "grid items-center gap-6 lg:grid-cols-[1.08fr_0.92fr] lg:gap-8"
        }
      >
        <div className="space-y-4">
          {eyebrow && <p className="brew-eyebrow text-brew-secondary">{eyebrow}</p>}
          <HeadingTag
            className={
              headingLevel === "h1" ? "brew-hero-heading" : "brew-page-heading"
            }
          >
            {title}
          </HeadingTag>
          {description && (
            <p className="max-w-xl text-[15px] leading-relaxed text-brew-secondary sm:text-base">
              {description}
            </p>
          )}
          {actions && <div className="flex flex-wrap items-center gap-3 pt-1">{actions}</div>}
          {children}
        </div>

        <Illustration
          name={illustration}
          alt={illustrationAlt}
          className={
            isStacked
              ? "mx-auto h-[210px] w-full max-w-[380px]"
              : "mx-auto h-[240px] w-full max-w-[440px] lg:h-[270px]"
          }
        />
      </div>
    </section>
  );
}
