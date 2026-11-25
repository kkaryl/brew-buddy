import type { JSX } from "react";
import type { AgendaItemResponse } from "../../api/types";

export function RunOfShowRibbon({
  segments,
  totalDurationMinutes,
}: {
  readonly segments: readonly AgendaItemResponse[];
  readonly totalDurationMinutes: number;
}): JSX.Element {
  const cumulativeStarts: number[] = [];
  let running = 0;
  for (const seg of segments) {
    cumulativeStarts.push(running);
    running += seg.duration_minutes;
  }

  const sumLabel = segments.map((s) => `${String(s.duration_minutes)}m`).join(" + ");
  const minVisualWeight = Math.max(1, Math.round(Math.max(1, totalDurationMinutes) * 0.18));
  const gridCols = segments
    .map((s) => `minmax(0, ${String(Math.max(minVisualWeight, s.duration_minutes))}fr)`)
    .join(" ");

  return (
    <div className="brew-card-paper min-w-0 overflow-hidden rounded-[26px] px-5 py-4.5">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <span className="brew-eyebrow">{String(totalDurationMinutes)}-MINUTE RUN OF SHOW</span>
        <span className="font-mono-code text-xs text-brew-secondary">{sumLabel}</span>
      </div>

      <ol
        className="grid gap-2 max-md:!grid-cols-1"
        style={{ gridTemplateColumns: gridCols || "minmax(0, 1fr)" }}
      >
        {segments.map((seg, idx) => {
          const startMin = cumulativeStarts[idx] ?? 0;
          const endMin = startMin + seg.duration_minutes;
          const surfaceClass =
            idx === 0
              ? "bg-brew-peach"
              : idx === segments.length - 1
                ? "bg-brew-mint"
                : "brew-card-lavender shadow-none";

          return (
            <li
              key={`${seg.title}-${String(idx)}`}
              className={`min-w-0 break-words rounded-[16px] px-3.5 py-3 ${surfaceClass}`}
            >
              <div className="text-[13px] font-extrabold text-brew-plum">
                {String(startMin)}-{String(endMin)}m · {seg.title}
              </div>
              <div
                className={`mt-0.5 text-[11.5px] leading-snug ${
                  idx === segments.length - 1 ? "text-[#235744]" : "text-brew-secondary"
                }`}
              >
                {seg.description}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
