import type { JSX } from "react";
import chatSetupHeroUrl from "../../assets/illustrations/chat-setup-hero.png";
import cueStudioCopilotUrl from "../../assets/illustrations/cue-studio-copilot.png";
import debriefKeepsakeJournalUrl from "../../assets/illustrations/debrief-keepsake-journal.png";
import homeClubWelcomeUrl from "../../assets/illustrations/home-club-welcome.svg";
import memoryBloomJournalUrl from "../../assets/illustrations/memory-bloom-journal.svg";
import peopleCircleClubUrl from "../../assets/illustrations/people-circle-club.svg";
import relationshipFolioCircleUrl from "../../assets/illustrations/relationship-folio-circle.png";

export type IllustrationName =
  | "chat-setup-hero"
  | "cue-studio-copilot"
  | "debrief-keepsake-journal"
  | "relationship-folio-circle"
  | "home-club-welcome"
  | "memory-bloom-journal"
  | "people-circle-club";

const ILLUSTRATION_SOURCES: Record<
  IllustrationName,
  { readonly src: string; readonly defaultAlt: string }
> = {
  "chat-setup-hero": {
    src: chatSetupHeroUrl,
    defaultAlt:
      "Two friendly professionals chatting warmly across an open pale ivory laptop with the brew wordmark",
  },
  "cue-studio-copilot": {
    src: cueStudioCopilotUrl,
    defaultAlt:
      "Friendly conversation co-pilot holding starred pale ivory cue cards framed by pastel shapes",
  },
  "debrief-keepsake-journal": {
    src: debriefKeepsakeJournalUrl,
    defaultAlt:
      "Smiling woman writing reflections into an open pastel journal alongside floating keepsake cards",
  },
  "relationship-folio-circle": {
    src: relationshipFolioCircleUrl,
    defaultAlt:
      "Three smiling colleagues standing together with a coral relationship folio and pastel circles",
  },
  "home-club-welcome": {
    src: homeClubWelcomeUrl,
    defaultAlt:
      "Friendly professional holding a coral relationship notebook framed by soft pastel circles",
  },
  "memory-bloom-journal": {
    src: memoryBloomJournalUrl,
    defaultAlt: "Open pastel relationship journal with an approved keepsake memory card",
  },
  "people-circle-club": {
    src: peopleCircleClubUrl,
    defaultAlt:
      "Two friendly counterparts framed by overlapping peach, lavender, and mint circles",
  },
};

export interface IllustrationProps {
  readonly name: IllustrationName;
  readonly alt?: string | undefined;
  readonly decorative?: boolean | undefined;
  readonly className?: string | undefined;
}

export function Illustration({
  name,
  alt,
  decorative = false,
  className = "",
}: IllustrationProps): JSX.Element {
  const asset = ILLUSTRATION_SOURCES[name];
  return (
    <div className={`flex items-center justify-center overflow-hidden ${className}`}>
      <img
        src={asset.src}
        alt={decorative ? "" : (alt ?? asset.defaultAlt)}
        aria-hidden={decorative ? "true" : undefined}
        decoding="async"
        className="h-full max-h-full w-auto max-w-full object-contain select-none"
      />
    </div>
  );
}
