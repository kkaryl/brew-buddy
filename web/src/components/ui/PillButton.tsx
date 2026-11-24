import type { ButtonHTMLAttributes, JSX, ReactNode } from "react";

export type PillButtonVariant =
  | "outline"
  | "peach"
  | "lavender"
  | "mint"
  | "ghost"
  | "danger";

export interface PillButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly children: ReactNode;
  readonly variant?: PillButtonVariant | undefined;
  readonly size?: "sm" | "md" | undefined;
}

const VARIANT_CLASSES: Record<PillButtonVariant, string> = {
  outline:
    "border border-brew-border bg-brew-paper text-brew-plum hover:border-brew-plum/25 hover:bg-brew-blush",
  peach:
    "border border-[#F5D6C7] bg-brew-peach text-brew-plum hover:brightness-97",
  lavender:
    "border border-[#DECFF8] bg-brew-lavender text-brew-plum hover:brightness-97",
  mint:
    "border border-[#C9E8D7] bg-brew-mint text-[#235744] hover:brightness-97",
  ghost:
    "border border-transparent bg-transparent text-brew-secondary hover:bg-brew-blush hover:text-brew-plum",
  danger:
    "border border-[#F4C4BC] bg-[#FFF0ED] text-[#9E3426] hover:bg-[#FFE3DD]",
};

const SIZE_CLASSES: Record<NonNullable<PillButtonProps["size"]>, string> = {
  sm: "min-h-[40px] px-3.5 py-1.5 text-xs",
  md: "min-h-[44px] px-4.5 py-2 text-sm",
};

export function PillButton({
  children,
  variant = "outline",
  size = "md",
  type = "button",
  className = "",
  ...rest
}: PillButtonProps): JSX.Element {
  return (
    <button
      type={type}
      className={`inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-full font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
