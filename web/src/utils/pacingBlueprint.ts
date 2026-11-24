export interface BlueprintSplit {
  readonly hookMinutes: number;
  readonly coreMinutes: number;
  readonly wrapMinutes: number;
  readonly questionTargetLabel: string;
}

export function computeBlueprintSplit(totalMinutes: number): BlueprintSplit {
  const safeTotal = Math.max(5, Math.min(180, Math.round(totalMinutes) || 30));
  if (safeTotal <= 15) {
    const hook = Math.max(1, Math.min(3, Math.round(safeTotal * 0.14)));
    const wrap = Math.max(1, Math.min(3, Math.round(safeTotal * 0.2)));
    const core = Math.max(1, safeTotal - hook - wrap);
    return {
      hookMinutes: hook,
      coreMinutes: core,
      wrapMinutes: wrap,
      questionTargetLabel: "2 High-Signal Questions",
    };
  }
  if (safeTotal <= 30) {
    const hook = 5;
    const wrap = 5;
    const core = Math.max(5, safeTotal - hook - wrap);
    return {
      hookMinutes: hook,
      coreMinutes: core,
      wrapMinutes: wrap,
      questionTargetLabel: "3-4 Focused Questions",
    };
  }
  const hook = Math.round(safeTotal * 0.14);
  const wrap = Math.round(safeTotal * 0.16);
  const core = Math.max(10, safeTotal - hook - wrap);
  return {
    hookMinutes: hook,
    coreMinutes: core,
    wrapMinutes: wrap,
    questionTargetLabel: "4-6 Deep-Dive Questions",
  };
}
