import { Star } from "lucide-react";
import type { JSX } from "react";
import type { ConversationQuestionResponse } from "../../api/types";

export interface CueQuestionCardProps {
  readonly item: ConversationQuestionResponse;
  readonly index: number;
  readonly isStarred: boolean;
  readonly onToggleStar?: (() => void) | undefined;
  readonly pocketOrderLabel?: string | undefined;
  readonly compact?: boolean | undefined;
}

export function CueQuestionCard({
  item,
  index,
  isStarred,
  onToggleStar,
  pocketOrderLabel,
  compact = false,
}: CueQuestionCardProps): JSX.Element {
  return (
    <li
      className={`flex flex-col justify-between gap-3 rounded-[24px] bg-brew-paper p-5 shadow-card transition ${
        isStarred ? "border-2 border-brew-coral" : "border border-brew-border"
      }`}
    >
      <div className="space-y-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="brew-badge-peach font-mono-code">
              {pocketOrderLabel ?? `Q${String(index + 1)}`}
            </span>
            {item.category && <span className="brew-badge-lavender">{item.category}</span>}
          </div>

          {onToggleStar && (
            <button
              id={`btn-star-question-${item.id}`}
              type="button"
              aria-pressed={isStarred}
              onClick={onToggleStar}
              className={`inline-flex min-h-[32px] cursor-pointer items-center gap-1 rounded-full px-2 py-1 text-xs transition ${
                isStarred
                  ? "font-bold text-[#9B4B35]"
                  : "font-medium text-brew-secondary hover:text-brew-plum"
              }`}
            >
              {isStarred ? (
                <>
                  <Star className="h-3.5 w-3.5 fill-current" aria-hidden="true" />
                  <span>Starred</span>
                </>
              ) : (
                <span>Tap to star</span>
              )}
            </button>
          )}
        </div>

        <p
          className={`font-serif leading-[1.32] font-bold text-brew-plum ${
            compact ? "text-[16.5px]" : isStarred ? "text-[17px]" : "text-base"
          }`}
        >
          {item.question}
        </p>
      </div>

      {(!compact || isStarred) && item.rationale && (
        <p className="border-t border-brew-border pt-2.5 text-xs leading-relaxed text-brew-secondary">
          <strong className="font-bold text-brew-plum">Why it works:</strong> {item.rationale}
        </p>
      )}
    </li>
  );
}
