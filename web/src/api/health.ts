export interface HealthPayload {
  readonly status: "ok" | "degraded";
  readonly service: string;
  readonly version: string;
  readonly environment: string;
  readonly model: string;
  readonly timestamp_utc: string;
}

export class HealthCheckError extends Error {
  public readonly code: string;

  public constructor(code: string, message: string) {
    super(message);
    this.name = "HealthCheckError";
    this.code = code;
  }
}

const DEFAULT_TIMEOUT_MS = 5000;

function isHealthPayload(value: unknown): value is HealthPayload {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    (record["status"] === "ok" || record["status"] === "degraded") &&
    typeof record["service"] === "string" &&
    typeof record["version"] === "string" &&
    typeof record["environment"] === "string" &&
    typeof record["model"] === "string" &&
    typeof record["timestamp_utc"] === "string"
  );
}

export async function fetchBackendHealth(
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<HealthPayload> {
  const baseUrl = (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "";
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${baseUrl}/api/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new HealthCheckError(
        "HTTP_ERROR",
        `Backend responded with HTTP ${String(response.status)}.`,
      );
    }

    const body: unknown = await response.json();
    if (!isHealthPayload(body)) {
      throw new HealthCheckError(
        "INVALID_PAYLOAD",
        "Backend returned an unexpected health payload shape.",
      );
    }

    return body;
  } catch (err: unknown) {
    if (err instanceof HealthCheckError) {
      throw err;
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new HealthCheckError(
        "TIMEOUT",
        `Backend health check timed out after ${String(timeoutMs)}ms.`,
      );
    }
    throw new HealthCheckError(
      "NETWORK_ERROR",
      "Unable to reach the Brew backend API.",
    );
  } finally {
    globalThis.clearTimeout(timer);
  }
}
