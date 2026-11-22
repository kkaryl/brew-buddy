import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("Brew foundation health view", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders backend status and configured Gemini model when /api/health succeeds", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "ok",
          service: "brew",
          version: "0.1.0",
          environment: "local",
          model: "gemini-3.8-flash",
          timestamp_utc: "2026-11-22T10:00:00+00:00",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Backend OK")).toBeInTheDocument();
    });
    expect(screen.getByText("brew v0.1.0")).toBeInTheDocument();
    expect(screen.getByText("gemini-3.8-flash")).toBeInTheDocument();
  });

  it("renders graceful offline alert when backend health request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new Error("Connection refused"),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Backend connection unavailable",
      );
    });
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });
});
