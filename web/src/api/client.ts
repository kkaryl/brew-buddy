import {
  refreshFirebaseIdToken,
  type VerifiedSignInTokens,
} from "../auth/googleFirebaseAuth";
import {
  clearStoredSession,
  isSessionExpired,
  saveStoredSession,
  type StoredAuthSession,
} from "../auth/session";
import type {
  ApiErrorResponse,
  ApproveMemoryProposalRequest,
  AuthClientConfigResponse,
  AuthenticatedPrincipalResponse,
  BriefRevisionListResponse,
  ContactListResponse,
  ContactResponse,
  CreateContactRequest,
  ErrorDetailItem,
  FirebaseClientConfigResponse,
  GenerateBriefRequest,
  MeetingListResponse,
  MemoryListResponse,
  MemoryProposalBatchResponse,
  MemoryProposalResponse,
  MemoryResponse,
  MemoryScope,
  MemoryType,
  MockSessionResponse,
  PreparationBriefResponse,
  ProposalStatus,
  ProposeMemoriesRequest,
  RejectMemoryProposalRequest,
  ReviseBriefRequest,
  UpdateMemoryRequest,
} from "./types";

const DEFAULT_TIMEOUT_MS = 12_000;
const WORKFLOW_TIMEOUT_MS = 90_000;

export class BrewApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly traceId: string | null;
  public readonly details: readonly ErrorDetailItem[];

  public constructor(options: {
    status: number;
    code: string;
    message: string;
    traceId?: string | null;
    details?: readonly ErrorDetailItem[];
  }) {
    super(options.message);
    this.name = "BrewApiError";
    this.status = options.status;
    this.code = options.code;
    this.traceId = options.traceId ?? null;
    this.details = options.details ?? [];
  }

  public get isUnauthorized(): boolean {
    return (
      this.status === 401 ||
      this.code === "AUTHENTICATION_REQUIRED" ||
      this.code === "TOKEN_EXPIRED"
    );
  }

  public get isVersionConflict(): boolean {
    return this.status === 409 && this.code === "VERSION_CONFLICT";
  }
}

function resolveApiBaseUrl(): string {
  const configured = import.meta.env["VITE_API_BASE_URL"] as string | undefined;
  if (!configured) {
    // Empty string issues same-origin `/api/...` calls in production and Vite dev proxy locally.
    return "";
  }
  return configured.replace(/\/+$/, "");
}

function generateIdempotencyKey(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${String(Date.now())}_${Math.random().toString(36).slice(2, 10)}`;
}

function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const outer = value as Record<string, unknown>;
  const err = outer["error"];
  if (typeof err !== "object" || err === null) {
    return false;
  }
  const errRecord = err as Record<string, unknown>;
  return (
    typeof errRecord["code"] === "string" &&
    typeof errRecord["message"] === "string" &&
    typeof errRecord["trace_id"] === "string"
  );
}

async function parseErrorFromResponse(response: Response): Promise<BrewApiError> {
  try {
    const body: unknown = await response.json();
    if (isApiErrorResponse(body)) {
      return new BrewApiError({
        status: response.status,
        code: body.error.code,
        message: body.error.message,
        traceId: body.error.trace_id,
        details: Array.isArray(body.error.details) ? body.error.details : [],
      });
    }
  } catch {
    // Fall back to HTTP status message below when body is not JSON.
  }

  return new BrewApiError({
    status: response.status,
    code: response.status === 401 ? "AUTHENTICATION_REQUIRED" : `HTTP_${String(response.status)}`,
    message:
      response.status === 401
        ? "Your session has expired or is unauthorized. Please sign in again."
        : `Request failed with HTTP ${String(response.status)}.`,
  });
}

export interface BrewApiClientOptions {
  readonly getSession: () => StoredAuthSession | null;
  readonly getFirebaseConfig?: () => FirebaseClientConfigResponse | null;
  readonly onSessionUpdated?: (session: StoredAuthSession) => void;
  readonly onUnauthorized?: (reason: string) => void;
}

export class BrewApiClient {
  private readonly baseUrl: string;
  private readonly options: BrewApiClientOptions;

  public constructor(options: BrewApiClientOptions) {
    this.baseUrl = resolveApiBaseUrl();
    this.options = options;
  }

  private async resolveValidBearerToken(): Promise<string> {
    const current = this.options.getSession();
    if (!current) {
      const message = "Please sign in to access your Brew workspace.";
      this.options.onUnauthorized?.(message);
      throw new BrewApiError({
        status: 401,
        code: "AUTHENTICATION_REQUIRED",
        message,
      });
    }

    if (!isSessionExpired(current)) {
      return current.accessToken;
    }

    const firebaseConfig = this.options.getFirebaseConfig?.() ?? null;
    if (current.refreshToken && firebaseConfig) {
      try {
        const refreshed: VerifiedSignInTokens = await refreshFirebaseIdToken(
          current.refreshToken,
          firebaseConfig,
        );
        const updatedSession: StoredAuthSession = {
          accessToken: refreshed.idToken,
          refreshToken: refreshed.refreshToken,
          expiresAtMs: refreshed.expiresAtMs,
          principal: current.principal,
        };
        saveStoredSession(updatedSession);
        this.options.onSessionUpdated?.(updatedSession);
        return updatedSession.accessToken;
      } catch {
        // Fall through to clean expiry logout below.
      }
    }

    clearStoredSession();
    const expiredMessage = "Your session has expired. Please sign in again.";
    this.options.onUnauthorized?.(expiredMessage);
    throw new BrewApiError({
      status: 401,
      code: "TOKEN_EXPIRED",
      message: expiredMessage,
    });
  }

  private async requestJson<T>(
    path: string,
    init: {
      readonly method: "GET" | "POST" | "PATCH" | "DELETE";
      readonly requiresAuth: boolean;
      readonly body?: unknown;
      readonly headers?: Readonly<Record<string, string>>;
      readonly timeoutMs?: number;
      readonly explicitBearerToken?: string;
    },
  ): Promise<T> {
    const timeoutMs = init.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(init.headers ?? {}),
    };

    if (init.requiresAuth) {
      const token = init.explicitBearerToken ?? (await this.resolveValidBearerToken());
      headers["Authorization"] = `Bearer ${token}`;
    }

    let serializedBody: string | undefined;
    if (init.body !== undefined) {
      headers["Content-Type"] = "application/json";
      serializedBody = JSON.stringify(init.body);
    }

    const controller = new AbortController();
    const timer = globalThis.setTimeout(() => controller.abort(), timeoutMs);

    try {
      const fetchInit: RequestInit = {
        method: init.method,
        headers,
        signal: controller.signal,
      };
      if (serializedBody !== undefined) {
        fetchInit.body = serializedBody;
      }

      const response = await fetch(`${this.baseUrl}${path}`, fetchInit);

      if (!response.ok) {
        const apiErr = await parseErrorFromResponse(response);
        if (init.requiresAuth && apiErr.isUnauthorized) {
          clearStoredSession();
          this.options.onUnauthorized?.(apiErr.message);
        }
        throw apiErr;
      }

      if (response.status === 204) {
        return undefined as T;
      }

      return (await response.json()) as T;
    } catch (err: unknown) {
      if (err instanceof BrewApiError) {
        throw err;
      }
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new BrewApiError({
          status: 504,
          code: "REQUEST_TIMEOUT",
          message: `Request timed out after ${String(Math.round(timeoutMs / 1000))}s. Please try again.`,
        });
      }
      throw new BrewApiError({
        status: 503,
        code: "NETWORK_ERROR",
        message: "Unable to reach the Brew server. Check your connection and try again.",
      });
    } finally {
      globalThis.clearTimeout(timer);
    }
  }

  public fetchAuthConfig(): Promise<AuthClientConfigResponse> {
    return this.requestJson<AuthClientConfigResponse>("/api/auth/config", {
      method: "GET",
      requiresAuth: false,
    });
  }

  public createLocalMockSession(personaId: string): Promise<MockSessionResponse> {
    return this.requestJson<MockSessionResponse>("/api/auth/mock-session", {
      method: "POST",
      requiresAuth: false,
      body: { persona_id: personaId },
    });
  }

  public async logoutSession(token: string | null): Promise<void> {
    if (!token) {
      return;
    }
    try {
      await this.requestJson<undefined>("/api/auth/logout", {
        method: "POST",
        requiresAuth: false,
        headers: { Authorization: `Bearer ${token}` },
        timeoutMs: 4_000,
      });
    } catch {
      // Sign-out clears client session regardless of network reachability.
    }
  }

  public verifyCurrentPrincipal(explicitBearerToken?: string): Promise<AuthenticatedPrincipalResponse> {
    const reqInit =
      explicitBearerToken !== undefined
        ? { method: "GET" as const, requiresAuth: true, explicitBearerToken }
        : { method: "GET" as const, requiresAuth: true };
    return this.requestJson<AuthenticatedPrincipalResponse>("/api/v1/auth/me", reqInit);
  }

  public listContacts(): Promise<ContactListResponse> {
    return this.requestJson<ContactListResponse>("/api/v1/contacts", {
      method: "GET",
      requiresAuth: true,
    });
  }

  public createContact(payload: CreateContactRequest): Promise<ContactResponse> {
    return this.requestJson<ContactResponse>("/api/v1/contacts", {
      method: "POST",
      requiresAuth: true,
      body: payload,
    });
  }

  public listMeetings(contactId?: string): Promise<MeetingListResponse> {
    const query = contactId ? `?contact_id=${encodeURIComponent(contactId)}` : "";
    return this.requestJson<MeetingListResponse>(`/api/v1/meetings${query}`, {
      method: "GET",
      requiresAuth: true,
    });
  }

  public generateBrief(
    payload: GenerateBriefRequest,
    idempotencyKey?: string,
  ): Promise<PreparationBriefResponse> {
    const resolvedKey = idempotencyKey ?? generateIdempotencyKey("gen");
    return this.requestJson<PreparationBriefResponse>("/api/v1/briefs/generate", {
      method: "POST",
      requiresAuth: true,
      body: payload,
      headers: { "Idempotency-Key": resolvedKey },
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    });
  }

  public getBrief(briefId: string): Promise<PreparationBriefResponse> {
    return this.requestJson<PreparationBriefResponse>(
      `/api/v1/briefs/${encodeURIComponent(briefId)}`,
      {
        method: "GET",
        requiresAuth: true,
      },
    );
  }

  public listBriefRevisions(briefId: string): Promise<BriefRevisionListResponse> {
    return this.requestJson<BriefRevisionListResponse>(
      `/api/v1/briefs/${encodeURIComponent(briefId)}/revisions`,
      {
        method: "GET",
        requiresAuth: true,
      },
    );
  }

  public reviseBrief(
    briefId: string,
    payload: ReviseBriefRequest,
    idempotencyKey?: string,
  ): Promise<PreparationBriefResponse> {
    const resolvedKey = idempotencyKey ?? generateIdempotencyKey("rev");
    return this.requestJson<PreparationBriefResponse>(
      `/api/v1/briefs/${encodeURIComponent(briefId)}/revise`,
      {
        method: "POST",
        requiresAuth: true,
        body: payload,
        headers: { "Idempotency-Key": resolvedKey },
        timeoutMs: WORKFLOW_TIMEOUT_MS,
      },
    );
  }

  public proposeMemories(payload: ProposeMemoriesRequest): Promise<MemoryProposalBatchResponse> {
    return this.requestJson<MemoryProposalBatchResponse>("/api/v1/memories/propose", {
      method: "POST",
      requiresAuth: true,
      body: payload,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    });
  }

  public listMemoryProposals(params?: {
    readonly status?: ProposalStatus;
    readonly contactId?: string;
  }): Promise<MemoryProposalBatchResponse> {
    const search = new URLSearchParams();
    if (params?.status) {
      search.set("status", params.status);
    }
    if (params?.contactId) {
      search.set("contact_id", params.contactId);
    }
    const qs = search.toString();
    return this.requestJson<MemoryProposalBatchResponse>(
      `/api/v1/memories/proposals${qs ? `?${qs}` : ""}`,
      {
        method: "GET",
        requiresAuth: true,
      },
    );
  }

  public approveMemoryProposal(
    proposalId: string,
    payload: ApproveMemoryProposalRequest,
  ): Promise<MemoryResponse> {
    return this.requestJson<MemoryResponse>(
      `/api/v1/memories/${encodeURIComponent(proposalId)}/approve`,
      {
        method: "POST",
        requiresAuth: true,
        body: payload,
      },
    );
  }

  public rejectMemoryProposal(
    proposalId: string,
    payload: RejectMemoryProposalRequest,
  ): Promise<MemoryProposalResponse> {
    return this.requestJson<MemoryProposalResponse>(
      `/api/v1/memories/${encodeURIComponent(proposalId)}/reject`,
      {
        method: "POST",
        requiresAuth: true,
        body: payload,
      },
    );
  }

  public listMemories(params?: {
    readonly scope?: MemoryScope;
    readonly contactId?: string;
    readonly memoryType?: MemoryType;
    readonly includeRevoked?: boolean;
    readonly includeSuperseded?: boolean;
  }): Promise<MemoryListResponse> {
    const search = new URLSearchParams();
    if (params?.scope) {
      search.set("scope", params.scope);
    }
    if (params?.contactId) {
      search.set("contact_id", params.contactId);
    }
    if (params?.memoryType) {
      search.set("memory_type", params.memoryType);
    }
    if (params?.includeRevoked) {
      search.set("include_revoked", "true");
    }
    if (params?.includeSuperseded) {
      search.set("include_superseded", "true");
    }
    const qs = search.toString();
    return this.requestJson<MemoryListResponse>(`/api/v1/memories${qs ? `?${qs}` : ""}`, {
      method: "GET",
      requiresAuth: true,
    });
  }

  public updateMemory(memoryId: string, payload: UpdateMemoryRequest): Promise<MemoryResponse> {
    return this.requestJson<MemoryResponse>(
      `/api/v1/memories/${encodeURIComponent(memoryId)}`,
      {
        method: "PATCH",
        requiresAuth: true,
        body: payload,
      },
    );
  }

  public deleteMemory(memoryId: string, expectedVersion?: number): Promise<void> {
    const query =
      expectedVersion !== undefined
        ? `?expected_version=${encodeURIComponent(String(expectedVersion))}`
        : "";
    return this.requestJson<undefined>(
      `/api/v1/memories/${encodeURIComponent(memoryId)}${query}`,
      {
        method: "DELETE",
        requiresAuth: true,
      },
    );
  }
}
