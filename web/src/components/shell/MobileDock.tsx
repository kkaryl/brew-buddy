import { Plus } from "lucide-react";
import type { JSX } from "react";
import type { MainSpace } from "./TopBarShell";

export interface MobileDockProps {
  readonly activeSpace: MainSpace;
  readonly onSelectSpace: (space: MainSpace) => void;
  readonly onOpenQuickSpark: () => void;
  readonly pendingProposalsCount: number;
}

const MOBILE_ITEMS: readonly {
  readonly id: MainSpace;
  readonly label: string;
}[] = [
  { id: "clubhouse", label: "Clubhouse" },
  { id: "studio", label: "Studio" },
  { id: "journal", label: "Journal" },
];

export function MobileDock({
  activeSpace,
  onSelectSpace,
  onOpenQuickSpark,
  pendingProposalsCount,
}: MobileDockProps): JSX.Element {
  return (
    <div className="fixed right-[18px] bottom-[18px] left-[18px] z-30 flex items-center justify-between gap-2 md:hidden">
      <nav
        aria-label="Mobile dock"
        className="flex flex-1 items-center justify-around rounded-full border border-brew-border bg-white/96 p-1.5 shadow-floating backdrop-blur-md"
      >
        {MOBILE_ITEMS.map((item) => {
          const isActive = activeSpace === item.id;
          const showBadge = item.id === "journal" && pendingProposalsCount > 0;
          return (
            <button
              key={item.id}
              id={`mobile-dock-${item.id}`}
              type="button"
              aria-current={isActive ? "page" : undefined}
              onClick={() => onSelectSpace(item.id)}
              className={`inline-flex min-h-[38px] cursor-pointer items-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-bold transition ${
                isActive
                  ? "bg-brew-peach text-brew-plum"
                  : "text-brew-secondary hover:text-brew-plum"
              }`}
            >
              <span>{item.label}</span>
              {showBadge && (
                <span className="inline-flex min-w-[16px] items-center justify-center rounded-full bg-brew-coral px-1 text-[10px] leading-4 font-extrabold text-brew-plum">
                  {String(pendingProposalsCount)}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <button
        id="mobile-dock-quick-spark"
        type="button"
        onClick={onOpenQuickSpark}
        aria-label="New conversation"
        className="flex h-12 w-12 shrink-0 cursor-pointer items-center justify-center rounded-full bg-brew-coral text-brew-plum shadow-floating transition hover:bg-brew-coral-vibrant"
      >
        <Plus className="h-5 w-5" strokeWidth={2.3} aria-hidden="true" />
      </button>
    </div>
  );
}
