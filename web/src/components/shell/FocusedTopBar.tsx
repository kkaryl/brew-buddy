import { ArrowLeft } from "lucide-react";
import type { JSX } from "react";
import { BrewLogo, ContactAvatar } from "../ui";

export interface FocusedTopBarProps {
  readonly backLabel: string;
  readonly backId?: string | undefined;
  readonly onBack: () => void;
  readonly onLogoClick?: (() => void) | undefined;
  readonly userDisplayName?: string | null | undefined;
  readonly onAvatarClick?: (() => void) | undefined;
  readonly centerEyebrow?: string | undefined;
  readonly mobileBackLabel?: string | undefined;
  readonly mobileCenterEyebrow?: string | undefined;
  readonly hideMobileAvatar?: boolean | undefined;
  readonly rightAction?:
    | {
        readonly label: string;
        readonly id?: string | undefined;
        readonly onClick: () => void;
      }
    | undefined;
}

export function FocusedTopBar({
  backLabel,
  backId = "btn-focused-back",
  onBack,
  onLogoClick,
  userDisplayName,
  onAvatarClick,
  centerEyebrow,
  mobileBackLabel,
  mobileCenterEyebrow,
  hideMobileAvatar = false,
  rightAction,
}: FocusedTopBarProps): JSX.Element {
  return (
    <header className="sticky top-0 z-30 bg-brew-bg/95 backdrop-blur-md md:h-[72px] md:border-b md:border-brew-border">
      <div className="mx-auto flex h-full max-w-[1440px] items-center justify-between gap-3 px-5 pt-4 pb-2.5 md:px-9 md:py-0">
        <button
          id={backId}
          type="button"
          onClick={onBack}
          className="inline-flex min-h-[38px] cursor-pointer items-center gap-1.5 rounded-full border border-brew-border bg-brew-paper px-4 py-2 text-[13px] font-semibold text-brew-plum transition hover:bg-brew-blush md:min-h-[40px]"
        >
          <ArrowLeft className="h-3.5 w-3.5 shrink-0" strokeWidth={2.2} aria-hidden="true" />
          {mobileBackLabel ? (
            <>
              <span className="md:hidden">{mobileBackLabel}</span>
              <span className="hidden md:inline">{backLabel}</span>
            </>
          ) : (
            <span>{backLabel}</span>
          )}
        </button>

        <div className="flex items-center justify-center">
          {centerEyebrow ? (
            <span className="brew-eyebrow">{centerEyebrow}</span>
          ) : mobileCenterEyebrow ? (
            <>
              <span className="brew-eyebrow md:hidden">{mobileCenterEyebrow}</span>
              <div className="hidden md:block">
                <BrewLogo size="md" onClick={onLogoClick} />
              </div>
            </>
          ) : (
            <BrewLogo size="md" onClick={onLogoClick} />
          )}
        </div>

        <div className="flex min-w-[40px] items-center justify-end">
          {rightAction ? (
            <button
              id={rightAction.id}
              type="button"
              onClick={rightAction.onClick}
              className="inline-flex min-h-[36px] cursor-pointer items-center rounded-full bg-brew-coral px-3.5 py-1.5 text-xs font-bold text-brew-plum transition hover:bg-brew-coral-vibrant"
            >
              {rightAction.label}
            </button>
          ) : userDisplayName ? (
            <div className={hideMobileAvatar ? "hidden md:block" : ""}>
              <ContactAvatar
                id="btn-focused-user-avatar"
                name={userDisplayName}
                tone="lavender"
                size="md"
                singleInitial
                onClick={onAvatarClick}
                ariaLabel={`Account and coaching style for ${userDisplayName}`}
              />
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
