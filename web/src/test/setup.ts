import "@testing-library/jest-dom/vitest";

// Prevent jsdom "Not implemented: HTMLCanvasElement.prototype.getContext" stderr noise during axe-core runs
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
}
