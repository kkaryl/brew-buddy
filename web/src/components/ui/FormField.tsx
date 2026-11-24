import type { JSX, ReactNode } from "react";

export interface FormFieldProps {
  readonly htmlFor: string;
  readonly label: string;
  readonly hideLabel?: boolean | undefined;
  readonly required?: boolean | undefined;
  readonly hint?: string | undefined;
  readonly error?: string | null | undefined;
  readonly errorId?: string | undefined;
  readonly children: ReactNode;
  readonly className?: string | undefined;
}

export function FormField({
  htmlFor,
  label,
  hideLabel = false,
  required = false,
  hint,
  error,
  errorId,
  children,
  className = "",
}: FormFieldProps): JSX.Element {
  const resolvedErrorId = errorId ?? `${htmlFor}-error`;
  return (
    <div className={`space-y-1.5 ${className}`}>
      {hideLabel ? (
        <label htmlFor={htmlFor} className="sr-only">
          {label}
        </label>
      ) : (
        <div className="flex items-baseline justify-between gap-2">
          <label htmlFor={htmlFor} className="block text-sm font-semibold text-brew-plum">
            {label}
            {required && <span className="ml-1 text-[#9E3426]">*</span>}
          </label>
          {hint && <span className="text-xs text-brew-secondary">{hint}</span>}
        </div>
      )}
      {children}
      {error && (
        <p
          id={resolvedErrorId}
          role="alert"
          className="text-xs font-medium text-[#B83B2A]"
        >
          {error}
        </p>
      )}
    </div>
  );
}
