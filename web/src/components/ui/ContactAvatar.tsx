import type { JSX } from "react";

export type AvatarTone = "lavender" | "peach" | "mint" | "coral" | "yellow";

export interface ContactAvatarProps {
  readonly name: string;
  readonly tone?: AvatarTone | undefined;
  readonly size?: "sm" | "md" | "lg" | undefined;
  readonly singleInitial?: boolean | undefined;
  readonly onClick?: (() => void) | undefined;
  readonly ariaLabel?: string | undefined;
  readonly id?: string | undefined;
  readonly className?: string | undefined;
}

const TONE_CLASSES: Record<AvatarTone, string> = {
  lavender: "bg-[#E9DFFC] text-[#302731] border-[#DDD0F8]",
  peach: "bg-[#FFE9DE] text-[#302731] border-[#F6D5C5]",
  mint: "bg-[#DDF3E7] text-[#265D49] border-[#C5E8D5]",
  coral: "bg-[#EF8B70]/25 text-[#302731] border-[#EF8B70]/40",
  yellow: "bg-[#FFF2CD] text-[#302731] border-[#F0DEA6]",
};

const SIZE_CLASSES: Record<NonNullable<ContactAvatarProps["size"]>, string> = {
  sm: "h-9 w-9 text-xs",
  md: "h-11 w-11 text-sm",
  lg: "h-14 w-14 text-base",
};

const TONE_ROTATION: readonly AvatarTone[] = ["peach", "lavender", "mint", "yellow", "coral"];

function resolveTone(name: string, explicitTone: AvatarTone | undefined): AvatarTone {
  if (explicitTone) {
    return explicitTone;
  }
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return TONE_ROTATION[hash % TONE_ROTATION.length] ?? "lavender";
}

function extractInitials(name: string, singleInitial: boolean): string {
  const parts = name
    .trim()
    .split(/\s+/)
    .filter((part) => part.length > 0);
  if (parts.length === 0) {
    return "B";
  }
  const first = parts[0]?.[0] ?? "B";
  if (singleInitial || parts.length === 1) {
    return first.toUpperCase();
  }
  const last = parts[parts.length - 1]?.[0] ?? "";
  return `${first}${last}`.toUpperCase();
}

export function ContactAvatar({
  name,
  tone,
  size = "md",
  singleInitial = false,
  onClick,
  ariaLabel,
  id,
  className = "",
}: ContactAvatarProps): JSX.Element {
  const resolvedTone = resolveTone(name, tone);
  const initials = extractInitials(name, singleInitial);
  const classes = `inline-flex shrink-0 items-center justify-center rounded-full border font-bold tracking-tight select-none ${TONE_CLASSES[resolvedTone]} ${SIZE_CLASSES[size]} ${className}`;

  if (onClick) {
    return (
      <button
        id={id}
        type="button"
        onClick={onClick}
        aria-label={ariaLabel ?? `${name} profile`}
        className={`${classes} min-h-[44px] min-w-[44px] cursor-pointer transition hover:brightness-95`}
      >
        {initials}
      </button>
    );
  }

  return (
    <span id={id} aria-hidden="true" className={classes}>
      {initials}
    </span>
  );
}
