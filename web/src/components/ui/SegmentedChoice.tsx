import type { JSX } from "react";

export interface SegmentedOption<T extends string> {
  readonly value: T;
  readonly label: string;
  readonly badge?: string | number | undefined;
  readonly id?: string | undefined;
}

export interface SegmentedChoiceProps<T extends string> {
  readonly options: readonly SegmentedOption<T>[];
  readonly value: T;
  readonly onChange: (next: T) => void;
  readonly ariaLabel: string;
  readonly mode?: "chips" | "tabs" | undefined;
  readonly idPrefix?: string | undefined;
}

export function SegmentedChoice<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  mode = "chips",
  idPrefix,
}: SegmentedChoiceProps<T>): JSX.Element {
  const isTabs = mode === "tabs";

  return (
    <div
      role={isTabs ? "tablist" : "group"}
      aria-label={ariaLabel}
      className="flex flex-wrap items-center gap-2"
    >
      {options.map((opt) => {
        const selected = opt.value === value;
        const resolvedId =
          opt.id ?? (idPrefix ? `${idPrefix}-${opt.value}` : undefined);

        return (
          <button
            key={opt.value}
            id={resolvedId}
            type="button"
            role={isTabs ? "tab" : undefined}
            aria-selected={isTabs ? selected : undefined}
            aria-pressed={isTabs ? undefined : selected}
            onClick={() => onChange(opt.value)}
            className={`inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-full border px-4 py-2 text-sm transition ${
              selected
                ? "border-[#F3CEBD] bg-brew-peach font-bold text-brew-plum shadow-xs"
                : "border-brew-border bg-brew-paper font-medium text-brew-secondary hover:border-brew-plum/20 hover:bg-brew-blush/60 hover:text-brew-plum"
            }`}
          >
            <span>{opt.label}</span>
            {opt.badge !== undefined && (
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-bold ${
                  selected
                    ? "bg-brew-paper/85 text-brew-plum"
                    : "bg-brew-lilac text-[#6E4AA3]"
                }`}
              >
                {String(opt.badge)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
