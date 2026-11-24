import { BookOpen, Compass, Plus, Sparkles, type LucideIcon } from "lucide-react";
import type { JSX } from "react";
import { BrewLogo, ContactAvatar } from "../ui";

export type MainSpace = "clubhouse" | "studio" | "journal";

export interface TopBarShellProps {
  readonly activeSpace: MainSpace;
  readonly onSelectSpace: (space: MainSpace) => void;
  readonly onOpenQuickSpark: () => void;
  readonly onOpenCoachingStyle: () => void;
  readonly userDisplayName: string;
  readonly pendingProposalsCount: number;
}

const SPACE_ITEMS: readonly {
  readonly id: MainSpace;
  readonly label: string;
  readonly icon: LucideIcon;
}[] = [
  { id: "clubhouse", label: "Clubhouse", icon: Compass },
  { id: "studio", label: "Cue Studio", icon: Sparkles },
  { id: "journal", label: "Relationship Journal", icon: BookOpen },
];

export function TopBarShell({
  activeSpace,
  onSelectSpace,
  onOpenQuickSpark,
  onOpenCoachingStyle,
  userDisplayName,
  pendingProposalsCount,
}: TopBarShellProps): JSX.Element {
  return (
    <header className="sticky top-0 z-30 bg-brew-bg/95 backdrop-blur-md md:h-[72px] md:border-b md:border-brew-border">
      <div className="mx-auto flex h-full max-w-[1440px] items-center justify-between gap-4 px-5 pt-4 pb-2.5 md:px-9 md:py-0">
        <div className="flex items-center gap-4">
          <BrewLogo
            id="btn-header-logo"
            size="md"
            onClick={() => onSelectSpace("clubhouse")}
          />
        </div>

        <nav
          aria-label="Primary navigation"
          className="hidden items-center gap-1.5 rounded-full border border-brew-border bg-brew-paper p-[5px] shadow-card md:inline-flex"
        >
          {SPACE_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activeSpace === item.id;
            const showBadge = item.id === "journal" && pendingProposalsCount > 0;
            return (
              <button
                key={item.id}
                id={`nav-space-${item.id}`}
                type="button"
                aria-current={isActive ? "page" : undefined}
                onClick={() => onSelectSpace(item.id)}
                className={`inline-flex min-h-[38px] cursor-pointer items-center gap-2 rounded-full px-5 py-2 text-[13.5px] whitespace-nowrap transition ${
                  isActive
                    ? "bg-brew-peach font-bold text-brew-plum"
                    : "font-semibold text-brew-secondary hover:bg-brew-blush/70 hover:text-brew-plum"
                }`}
              >
                <Icon
                  className="h-[15px] w-[15px] shrink-0"
                  strokeWidth={isActive ? 2.2 : 1.95}
                  aria-hidden="true"
                />
                <span>{item.label}</span>
                {showBadge && (
                  <span
                    aria-label={`${String(pendingProposalsCount)} keepsakes to review`}
                    className="brew-badge-coral"
                  >
                    {String(pendingProposalsCount)}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="flex items-center gap-3">
          <button
            id="btn-header-quick-spark"
            type="button"
            onClick={onOpenQuickSpark}
            className="hidden min-h-[38px] cursor-pointer items-center gap-1.5 rounded-full bg-brew-coral px-[18px] py-2 text-[13px] font-bold text-brew-plum transition hover:bg-brew-coral-vibrant md:inline-flex"
          >
            <Plus className="h-3.5 w-3.5 shrink-0" strokeWidth={2.4} aria-hidden="true" />
            <span>Quick Spark</span>
          </button>

          <ContactAvatar
            id="btn-header-user-avatar"
            name={userDisplayName}
            tone="lavender"
            size="md"
            singleInitial
            onClick={onOpenCoachingStyle}
            ariaLabel={`Account and coaching style for ${userDisplayName}`}
          />
        </div>
      </div>
    </header>
  );
}
