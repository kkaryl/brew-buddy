import type { ButtonHTMLAttributes, JSX, ReactNode } from "react";

export interface PrimaryButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly children: ReactNode;
  readonly tone?: "dark" | "coral" | undefined;
  readonly shape?: "rounded" | "pill" | undefined;
  readonly loading?: boolean | undefined;
  readonly fullWidth?: boolean | undefined;
}

export function PrimaryButton({
  children,
  tone = "dark",
  shape = "rounded",
  loading = false,
  fullWidth = false,
  disabled,
  type = "button",
  className = "",
  ...rest
}: PrimaryButtonProps): JSX.Element {
  const toneClasses =
    tone === "coral"
      ? "bg-brew-coral text-brew-plum hover:bg-brew-coral-vibrant hover:text-white"
      : "bg-brew-dark-btn text-white hover:bg-brew-dark-btn-hover";

  const radiusClass = shape === "pill" ? "rounded-full" : "rounded-btn-primary";
  const widthClass = fullWidth ? "w-full" : "";

  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`inline-flex min-h-[46px] cursor-pointer items-center justify-center gap-2 px-6 py-3 text-sm font-semibold shadow-card transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 ${toneClasses} ${radiusClass} ${widthClass} ${className}`}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden="true"
          className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  );
}
