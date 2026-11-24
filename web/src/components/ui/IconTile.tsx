import type { LucideIcon } from "lucide-react";
import type { JSX } from "react";

export type IconTileTone = "peach" | "coral" | "lavender" | "mint" | "yellow" | "plum";

export interface IconTileProps {
  readonly icon: LucideIcon;
  readonly tone?: IconTileTone | undefined;
  readonly size?: "sm" | "md" | "lg" | undefined;
}

const TONE_CLASSES: Record<IconTileTone, string> = {
  peach: "bg-[#FFE9DE] text-[#302731]",
  coral: "bg-[#EF8B70]/22 text-[#C4593E]",
  lavender: "bg-[#E9DFFC] text-[#6B4A9E]",
  mint: "bg-[#DDF3E7] text-[#2D7A5E]",
  yellow: "bg-[#FFF2CD] text-[#7D6020]",
  plum: "bg-[#342B36] text-[#FFFFFF]",
};

const SIZE_CLASSES: Record<
  NonNullable<IconTileProps["size"]>,
  { readonly box: string; readonly icon: string }
> = {
  sm: { box: "h-9 w-9 rounded-xl", icon: "h-4 w-4" },
  md: { box: "h-11 w-11 rounded-2xl", icon: "h-5 w-5" },
  lg: { box: "h-13 w-13 rounded-[18px]", icon: "h-6 w-6" },
};

export function IconTile({
  icon: Icon,
  tone = "peach",
  size = "md",
}: IconTileProps): JSX.Element {
  const dims = SIZE_CLASSES[size];
  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center ${dims.box} ${TONE_CLASSES[tone]}`}
    >
      <Icon className={dims.icon} strokeWidth={2} />
    </span>
  );
}
