import { useCallback, useEffect, useMemo, useRef, useState, type JSX } from "react";
import { BrewApiClient, BrewApiError } from "./api/client";
import { fetchBackendHealth, type HealthPayload } from "./api/health";
import type {
  ApproveMemoryProposalRequest,
  AuthClientConfigResponse,
  ContactResponse,
  CreateContactRequest,
  GenerateBriefRequest,
  MeetingResponse,
  MemoryProposalBatchResponse,
  MemoryProposalResponse,
  MemoryResponse,
  PreparationBriefResponse,
  ProposeMemoriesRequest,
  RejectMemoryProposalRequest,
  ReviseBriefRequest,
  UpdateMemoryRequest,
} from "./api/types";
import type { VerifiedSignInTokens } from "./auth/googleFirebaseAuth";
import {
  clearStoredSession,
  isSessionExpired,
  loadStoredSession,
  saveStoredSession,
  type StoredAuthSession,
} from "./auth/session";
import { AuthSignInGate } from "./components/AuthSignInGate";
import { ContactFormModal } from "./components/ContactFormModal";
import { errorToFeedbackNotice } from "./components/formatters";
import { MemoryReviewWorkspace } from "./components/MemoryReviewWorkspace";
import { MemoryVaultWorkspace } from "./components/MemoryVaultWorkspace";
import { PrepareWorkspace } from "./components/PrepareWorkspace";
import { EmptyStateCard, StatusBanner } from "./components/StatusFeedback";

type ActiveNavSection = "prepare" | "review" | "memories" | "people";

type HealthViewState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly data: HealthPayload }
  | { readonly kind: "error"; readonly message: string };

export function App(): JSX.Element {
  const [healthState, setHealthState] = useState<HealthViewState>({ kind: "loading" });
  const [authConfig, setAuthConfig] = useState<AuthClientConfigResponse | null>(null);
  const [authConfigError, setAuthConfigError] = useState<string | null>(null);

  const [session, setSession] = useState<StoredAuthSession | null>(() => {
    const stored = loadStoredSession();
    if (stored && isSessionExpired(stored) && !stored.refreshToken) {
      clearStoredSession();
      return null;
    }
    return stored;
  });
  const [sessionExpiredReason, setSessionExpiredReason] = useState<string | null>(null);

  const [navSection, setNavSection] = useState<ActiveNavSection>("prepare");
  const [isContactModalOpen, setIsContactModalOpen] = useState(false);

  const [contacts, setContacts] = useState<readonly ContactResponse[]>([]);
  const [activeContactId, setActiveContactId] = useState<string | null>(null);
  const [meetings, setMeetings] = useState<readonly MeetingResponse[]>([]);
  const [activeBrief, setActiveBrief] = useState<PreparationBriefResponse | null>(null);
  const [briefRevisions, setBriefRevisions] = useState<readonly PreparationBriefResponse[]>([]);
  const [pendingProposals, setPendingProposals] = useState<readonly MemoryProposalResponse[]>([]);
  const [memories, setMemories] = useState<readonly MemoryResponse[]>([]);
  const [includeSuperseded, setIncludeSuperseded] = useState(false);

  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  const sessionRef = useRef<StoredAuthSession | null>(session);
  sessionRef.current = session;

  const authConfigRef = useRef<AuthClientConfigResponse | null>(authConfig);
  authConfigRef.current = authConfig;

  const resetAuthenticatedState = useCallback((expiredReason: string | null): void => {
    clearStoredSession();
    sessionRef.current = null;
    setSession(null);
    setContacts([]);
    setActiveContactId(null);
    setMeetings([]);
    setActiveBrief(null);
    setBriefRevisions([]);
    setPendingProposals([]);
    setMemories([]);
    if (expiredReason) {
      setSessionExpiredReason(expiredReason);
    }
  }, []);

  const apiClient = useMemo(
    () =>
      new BrewApiClient({
        getSession: () => sessionRef.current,
        getFirebaseConfig: () => authConfigRef.current?.firebase ?? null,
        onSessionUpdated: (updated) => {
          sessionRef.current = updated;
          setSession(updated);
        },
        onUnauthorized: (reason) => {
          resetAuthenticatedState(reason);
        },
      }),
    [resetAuthenticatedState],
  );

  const refreshRuntimeBootstrap = useCallback(async (): Promise<void> => {
    setHealthState({ kind: "loading" });
    setAuthConfigError(null);

    const [healthOutcome, authOutcome] = await Promise.allSettled([
      fetchBackendHealth(),
      apiClient.fetchAuthConfig(),
    ]);

    if (healthOutcome.status === "fulfilled") {
      setHealthState({ kind: "ready", data: healthOutcome.value });
    } else {
      const msg =
        healthOutcome.reason instanceof Error
          ? healthOutcome.reason.message
          : "Unable to reach the Brew backend API.";
      setHealthState({ kind: "error", message: msg });
    }

    if (authOutcome.status === "fulfilled") {
      setAuthConfig(authOutcome.value);
    } else {
      const msg =
        authOutcome.reason instanceof Error
          ? authOutcome.reason.message
          : "Unable to load authentication settings.";
      setAuthConfigError(msg);
    }
  }, [apiClient]);

  useEffect(() => {
    void refreshRuntimeBootstrap();
  }, [refreshRuntimeBootstrap]);

  const loadBriefWithRevisions = useCallback(
    async (briefId: string): Promise<void> => {
      const [brief, revisionsResp] = await Promise.all([
        apiClient.getBrief(briefId),
        apiClient.listBriefRevisions(briefId),
      ]);
      setActiveBrief(brief);
      setBriefRevisions(revisionsResp.items);
    },
    [apiClient],
  );

  const loadContactContext = useCallback(
    async (contactId: string): Promise<void> => {
      setLoadingWorkspace(true);
      setWorkspaceError(null);
      try {
        const meetingsResp = await apiClient.listMeetings(contactId);
        setMeetings(meetingsResp.items);
        const latestWithBrief = meetingsResp.items.find(
          (m) => typeof m.latest_brief_id === "string" && m.latest_brief_id.length > 0,
        );
        if (latestWithBrief?.latest_brief_id) {
          await loadBriefWithRevisions(latestWithBrief.latest_brief_id);
        } else {
          setActiveBrief(null);
          setBriefRevisions([]);
        }
      } catch (err: unknown) {
        if (!(err instanceof BrewApiError && err.isUnauthorized)) {
          setWorkspaceError(errorToFeedbackNotice(err, "Failed to load contact session").message ?? null);
        }
      } finally {
        setLoadingWorkspace(false);
      }
    },
    [apiClient, loadBriefWithRevisions],
  );

  const refreshMemoriesAndProposals = useCallback(
    async (showSuperseded: boolean): Promise<void> => {
      const [proposalsResp, memoriesResp] = await Promise.all([
        apiClient.listMemoryProposals({ status: "pending" }),
        apiClient.listMemories({ includeSuperseded: showSuperseded }),
      ]);
      setPendingProposals(proposalsResp.proposals);
      setMemories(memoriesResp.items);
    },
    [apiClient],
  );

  const hydrateAuthenticatedWorkspace = useCallback(
    async (showSuperseded: boolean): Promise<void> => {
      setLoadingWorkspace(true);
      setWorkspaceError(null);
      try {
        await apiClient.verifyCurrentPrincipal();
        const [contactsResp, proposalsResp, memoriesResp] = await Promise.all([
          apiClient.listContacts(),
          apiClient.listMemoryProposals({ status: "pending" }),
          apiClient.listMemories({ includeSuperseded: showSuperseded }),
        ]);
        setContacts(contactsResp.items);
        setPendingProposals(proposalsResp.proposals);
        setMemories(memoriesResp.items);

        const firstContact = contactsResp.items[0];
        if (firstContact) {
          setActiveContactId(firstContact.id);
          await loadContactContext(firstContact.id);
        } else {
          setActiveContactId(null);
          setMeetings([]);
          setActiveBrief(null);
          setBriefRevisions([]);
        }
      } catch (err: unknown) {
        if (!(err instanceof BrewApiError && err.isUnauthorized)) {
          setWorkspaceError(
            errorToFeedbackNotice(err, "Failed to load your workspace").message ?? null,
          );
        }
      } finally {
        setLoadingWorkspace(false);
      }
    },
    [apiClient, loadContactContext],
  );

  const activeSessionToken = session?.accessToken ?? null;

  useEffect(() => {
    if (!activeSessionToken) {
      return;
    }
    void hydrateAuthenticatedWorkspace(false);
  }, [activeSessionToken, hydrateAuthenticatedWorkspace]);

  const handleVerifiedTokenSignIn = useCallback(
    async (tokens: VerifiedSignInTokens): Promise<void> => {
      const principal = await apiClient.verifyCurrentPrincipal(tokens.idToken);
      const nextSession: StoredAuthSession = {
        accessToken: tokens.idToken,
        refreshToken: tokens.refreshToken,
        expiresAtMs: tokens.expiresAtMs,
        principal,
      };
      saveStoredSession(nextSession);
      sessionRef.current = nextSession;
      setSessionExpiredReason(null);
      setSession(nextSession);
    },
    [apiClient],
  );

  const handleLocalMockSignIn = useCallback(
    async (personaId: string): Promise<void> => {
      const mockResp = await apiClient.createLocalMockSession(personaId);
      const parsedExpiry = Date.parse(mockResp.expires_at);
      const nextSession: StoredAuthSession = {
        accessToken: mockResp.access_token,
        refreshToken: null,
        expiresAtMs: Number.isNaN(parsedExpiry) ? null : parsedExpiry,
        principal: mockResp.principal,
      };
      saveStoredSession(nextSession);
      sessionRef.current = nextSession;
      setSessionExpiredReason(null);
      setSession(nextSession);
    },
    [apiClient],
  );

  const handleSignOut = useCallback(async (): Promise<void> => {
    const token = sessionRef.current?.accessToken ?? null;
    resetAuthenticatedState(null);
    await apiClient.logoutSession(token);
  }, [apiClient, resetAuthenticatedState]);

  const handleSelectContact = useCallback(
    async (contactId: string): Promise<void> => {
      setActiveContactId(contactId);
      setNavSection("prepare");
      await loadContactContext(contactId);
    },
    [loadContactContext],
  );

  const handleCreateContact = useCallback(
    async (payload: CreateContactRequest): Promise<ContactResponse> => {
      const created = await apiClient.createContact(payload);
      setContacts((prev) => [created, ...prev]);
      setActiveContactId(created.id);
      setMeetings([]);
      setActiveBrief(null);
      setBriefRevisions([]);
      setNavSection("prepare");
      return created;
    },
    [apiClient],
  );

  const handleGenerateBrief = useCallback(
    async (payload: GenerateBriefRequest): Promise<PreparationBriefResponse> => {
      const created = await apiClient.generateBrief(payload);
      const [meetingsResp, revisionsResp] = await Promise.all([
        apiClient.listMeetings(payload.contact_id),
        apiClient.listBriefRevisions(created.id),
      ]);
      setMeetings(meetingsResp.items);
      setActiveBrief(created);
      setBriefRevisions(revisionsResp.items);
      return created;
    },
    [apiClient],
  );

  const handleReviseBrief = useCallback(
    async (briefId: string, payload: ReviseBriefRequest): Promise<PreparationBriefResponse> => {
      const updated = await apiClient.reviseBrief(briefId, payload);
      const revisionsResp = await apiClient.listBriefRevisions(briefId);
      setActiveBrief(updated);
      setBriefRevisions(revisionsResp.items);
      if (activeContactId) {
        const meetingsResp = await apiClient.listMeetings(activeContactId);
        setMeetings(meetingsResp.items);
      }
      return updated;
    },
    [activeContactId, apiClient],
  );

  const handleProposeMemories = useCallback(
    async (payload: ProposeMemoriesRequest): Promise<MemoryProposalBatchResponse> => {
      const batch = await apiClient.proposeMemories(payload);
      await refreshMemoriesAndProposals(includeSuperseded);
      return batch;
    },
    [apiClient, includeSuperseded, refreshMemoriesAndProposals],
  );

  const handleApproveProposal = useCallback(
    async (
      proposalId: string,
      payload: ApproveMemoryProposalRequest,
    ): Promise<MemoryResponse> => {
      const approved = await apiClient.approveMemoryProposal(proposalId, payload);
      await refreshMemoriesAndProposals(includeSuperseded);
      return approved;
    },
    [apiClient, includeSuperseded, refreshMemoriesAndProposals],
  );

  const handleRejectProposal = useCallback(
    async (
      proposalId: string,
      payload: RejectMemoryProposalRequest,
    ): Promise<MemoryProposalResponse> => {
      const rejected = await apiClient.rejectMemoryProposal(proposalId, payload);
      await refreshMemoriesAndProposals(includeSuperseded);
      return rejected;
    },
    [apiClient, includeSuperseded, refreshMemoriesAndProposals],
  );

  const handleToggleIncludeSuperseded = useCallback(
    async (next: boolean): Promise<void> => {
      setIncludeSuperseded(next);
      try {
        const memoriesResp = await apiClient.listMemories({ includeSuperseded: next });
        setMemories(memoriesResp.items);
      } catch (err: unknown) {
        if (!(err instanceof BrewApiError && err.isUnauthorized)) {
          setWorkspaceError(errorToFeedbackNotice(err, "Could not load memories").message ?? null);
        }
      }
    },
    [apiClient],
  );

  const handleUpdateMemory = useCallback(
    async (memoryId: string, payload: UpdateMemoryRequest): Promise<MemoryResponse> => {
      const updated = await apiClient.updateMemory(memoryId, payload);
      await refreshMemoriesAndProposals(includeSuperseded);
      return updated;
    },
    [apiClient, includeSuperseded, refreshMemoriesAndProposals],
  );

  const handleDeleteMemory = useCallback(
    async (memoryId: string, expectedVersion: number): Promise<void> => {
      await apiClient.deleteMemory(memoryId, expectedVersion);
      await refreshMemoriesAndProposals(includeSuperseded);
    },
    [apiClient, includeSuperseded, refreshMemoriesAndProposals],
  );

  if (!session) {
    return (
      <AuthSignInGate
        health={healthState}
        authConfig={authConfig}
        authConfigError={authConfigError}
        sessionExpiredReason={sessionExpiredReason}
        onRefreshStatus={() => {
          void refreshRuntimeBootstrap();
        }}
        onVerifiedTokenSignIn={handleVerifiedTokenSignIn}
        onLocalMockSignIn={handleLocalMockSignIn}
      />
    );
  }

  const activeContact = contacts.find((c) => c.id === activeContactId) ?? null;
  const activeMeeting =
    (activeBrief
      ? meetings.find((m) => m.id === activeBrief.meeting_id)
      : meetings[0]) ?? null;

  const displayName = session.principal.display_name ?? session.principal.user_id;
  const isLocalMock = session.principal.auth_provider === "local_mock";

  return (
    <div className="min-h-screen bg-[#FAF6F0] text-[#23170F]">
      <a href="#main-workspace" className="md-skip-link">
        Skip to workspace
      </a>

      {/* Mobile Sticky Top App Bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between gap-2 border-b border-[#D6C7B7] bg-[#FAF6F0]/95 px-4 py-2.5 backdrop-blur lg:hidden">
        <div className="flex min-w-0 items-center gap-2">
          <span className="font-display shrink-0 text-xl font-semibold text-[#23170F]">Brew</span>
          {activeContact && (
            <button
              id="btn-mobile-active-contact"
              type="button"
              onClick={() => setNavSection("people")}
              className="md-badge md-badge-espresso max-w-[132px] truncate"
            >
              {activeContact.name}
            </button>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            id="btn-mobile-new-contact"
            type="button"
            onClick={() => setIsContactModalOpen(true)}
            className="md-btn md-btn-tonal min-h-9 px-3 py-1 text-xs whitespace-nowrap"
          >
            + New
          </button>
          <button
            id="btn-mobile-sign-out"
            type="button"
            onClick={() => {
              void handleSignOut();
            }}
            className="md-btn md-btn-text min-h-9 px-2.5 py-1 text-xs whitespace-nowrap"
          >
            Sign out
          </button>
        </div>
      </header>

      <div className="mx-auto grid min-h-screen max-w-7xl lg:grid-cols-[280px_minmax(0,1fr)]">
        {/* Desktop Persistent Navigation Drawer / Rail */}
        <aside
          aria-label="Workspace navigation"
          className="hidden border-r border-[#D6C7B7] bg-[#F5EEE4] lg:flex lg:flex-col lg:justify-between lg:p-5"
        >
          <div className="space-y-6">
            <div className="flex items-center justify-between px-1">
              <span className="font-display text-2xl font-semibold text-[#23170F]">Brew</span>
              {healthState.kind === "ready" && (
                <span className="md-badge md-badge-sage">Live</span>
              )}
            </div>

            <nav aria-label="Primary sections" className="space-y-1">
              <DesktopNavItem
                id="nav-desktop-prepare"
                label="Prepare"
                active={navSection === "prepare"}
                onClick={() => setNavSection("prepare")}
              />
              <DesktopNavItem
                id="nav-desktop-review"
                label="Notes & Review"
                badgeCount={pendingProposals.length}
                active={navSection === "review"}
                onClick={() => setNavSection("review")}
              />
              <DesktopNavItem
                id="nav-desktop-memories"
                label="Relationship Memory"
                badgeCount={memories.filter((m) => m.lifecycle_state === "approved").length}
                active={navSection === "memories"}
                onClick={() => setNavSection("memories")}
              />
            </nav>

            <div className="space-y-2.5 border-t border-[#D6C7B7] pt-5">
              <div className="flex items-center justify-between px-1">
                <span className="text-xs font-semibold tracking-wide text-[#594638] uppercase">
                  Counterparts
                </span>
                <button
                  id="btn-sidebar-new-contact"
                  type="button"
                  onClick={() => setIsContactModalOpen(true)}
                  className="text-xs font-semibold text-[#4A2E1B] hover:underline"
                >
                  + Add
                </button>
              </div>

              {contacts.length === 0 ? (
                <p className="px-1 text-xs text-[#594638]">No counterparts saved yet.</p>
              ) : (
                <ul className="max-h-72 space-y-1 overflow-y-auto pr-1">
                  {contacts.map((contact) => {
                    const isSelected = contact.id === activeContactId;
                    return (
                      <li key={contact.id}>
                        <button
                          id={`sidebar-contact-${contact.id}`}
                          type="button"
                          onClick={() => {
                            void handleSelectContact(contact.id);
                          }}
                          className={`flex w-full flex-col items-start rounded-xl px-3 py-2 text-left transition ${
                            isSelected
                              ? "bg-[#EAD8C7] font-semibold text-[#2B170A]"
                              : "text-[#23170F] hover:bg-[#EDE3D5]"
                          }`}
                        >
                          <span className="w-full truncate text-sm">{contact.name}</span>
                          {(contact.title || contact.organization) && (
                            <span className="w-full truncate text-xs font-normal text-[#594638]">
                              {[contact.title, contact.organization].filter(Boolean).join(" · ")}
                            </span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>

          <div className="space-y-2 border-t border-[#D6C7B7] pt-4">
            <div className="px-1">
              <p className="truncate text-sm font-semibold text-[#23170F]">{displayName}</p>
              <p className="text-xs text-[#594638]">
                {isLocalMock ? "Local isolated test session" : "Verified Google account"}
              </p>
            </div>
            <button
              id="btn-desktop-sign-out"
              type="button"
              onClick={() => {
                void handleSignOut();
              }}
              className="md-btn md-btn-outlined w-full text-xs"
            >
              Sign out
            </button>
          </div>
        </aside>

        {/* Main Workspace Canvas */}
        <main
          id="main-workspace"
          className="min-w-0 px-4 pt-6 pb-28 sm:px-8 lg:py-8 lg:pb-12"
        >
          <div className="mx-auto max-w-4xl space-y-6">
            {workspaceError && (
              <StatusBanner
                notice={{
                  kind: "error",
                  title: "Workspace error",
                  message: workspaceError,
                }}
                onDismiss={() => setWorkspaceError(null)}
              />
            )}

            {navSection === "prepare" && (
              <PrepareWorkspace
                activeContact={activeContact}
                meetings={meetings}
                activeBrief={activeBrief}
                briefRevisions={briefRevisions}
                loadingWorkspace={loadingWorkspace}
                onOpenNewContact={() => setIsContactModalOpen(true)}
                onSelectMeetingBrief={loadBriefWithRevisions}
                onGenerateBrief={handleGenerateBrief}
                onReviseBrief={handleReviseBrief}
                onReloadBrief={loadBriefWithRevisions}
                onJumpToPostMeetingNotes={() => setNavSection("review")}
              />
            )}

            {navSection === "review" && (
              <MemoryReviewWorkspace
                contacts={contacts}
                activeContact={activeContact}
                activeMeeting={activeMeeting}
                activeBrief={activeBrief}
                pendingProposals={pendingProposals}
                onProposeMemories={handleProposeMemories}
                onApproveProposal={handleApproveProposal}
                onRejectProposal={handleRejectProposal}
              />
            )}

            {navSection === "memories" && (
              <MemoryVaultWorkspace
                contacts={contacts}
                activeContact={activeContact}
                memories={memories}
                includeSuperseded={includeSuperseded}
                onToggleIncludeSuperseded={(next) => {
                  void handleToggleIncludeSuperseded(next);
                }}
                onUpdateMemory={handleUpdateMemory}
                onDeleteMemory={handleDeleteMemory}
              />
            )}

            {navSection === "people" && (
              <MobilePeopleDirectory
                contacts={contacts}
                activeContactId={activeContactId}
                displayName={displayName}
                isLocalMock={isLocalMock}
                onSelectContact={(contactId) => {
                  void handleSelectContact(contactId);
                }}
                onOpenNewContact={() => setIsContactModalOpen(true)}
              />
            )}
          </div>
        </main>
      </div>

      {/* Mobile Bottom Navigation Bar */}
      <nav
        aria-label="Mobile workspace navigation"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-[#D6C7B7] bg-[#F5EEE4]/98 px-2 py-1.5 backdrop-blur lg:hidden"
      >
        <MobileNavButton
          id="nav-mobile-prepare"
          label="Prepare"
          active={navSection === "prepare"}
          onClick={() => setNavSection("prepare")}
        />
        <MobileNavButton
          id="nav-mobile-review"
          label="Review"
          badgeCount={pendingProposals.length}
          active={navSection === "review"}
          onClick={() => setNavSection("review")}
        />
        <MobileNavButton
          id="nav-mobile-memories"
          label="Memory"
          active={navSection === "memories"}
          onClick={() => setNavSection("memories")}
        />
        <MobileNavButton
          id="nav-mobile-people"
          label="People"
          active={navSection === "people"}
          onClick={() => setNavSection("people")}
        />
      </nav>

      <ContactFormModal
        isOpen={isContactModalOpen}
        onClose={() => setIsContactModalOpen(false)}
        onCreateContact={handleCreateContact}
      />
    </div>
  );
}

function DesktopNavItem({
  id,
  label,
  badgeCount,
  active,
  onClick,
}: {
  readonly id: string;
  readonly label: string;
  readonly badgeCount?: number;
  readonly active: boolean;
  readonly onClick: () => void;
}): JSX.Element {
  return (
    <button
      id={id}
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={`flex min-h-11 w-full items-center justify-between rounded-full px-4 py-2 text-sm font-medium transition ${
        active
          ? "bg-[#4A2E1B] font-semibold text-[#FFFBF7]"
          : "text-[#23170F] hover:bg-[#EDE3D5]"
      }`}
    >
      <span>{label}</span>
      {badgeCount !== undefined && badgeCount > 0 && (
        <span
          className={`rounded-full px-2 py-0.5 font-mono-code text-xs font-semibold ${
            active ? "bg-[#FFFBF7]/20 text-[#FFFBF7]" : "bg-[#EAD8C7] text-[#2B170A]"
          }`}
        >
          {String(badgeCount)}
        </span>
      )}
    </button>
  );
}

function MobileNavButton({
  id,
  label,
  badgeCount,
  active,
  onClick,
}: {
  readonly id: string;
  readonly label: string;
  readonly badgeCount?: number;
  readonly active: boolean;
  readonly onClick: () => void;
}): JSX.Element {
  return (
    <button
      id={id}
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={`flex min-h-12 flex-col items-center justify-center rounded-2xl px-2 py-1 text-xs font-semibold transition ${
        active ? "bg-[#EAD8C7] text-[#2B170A]" : "text-[#594638]"
      }`}
    >
      <span className="flex items-center gap-1">
        <span>{label}</span>
        {badgeCount !== undefined && badgeCount > 0 && (
          <span className="rounded-full bg-[#4A2E1B] px-1.5 py-0.2 font-mono-code text-[0.68rem] text-[#FFFBF7]">
            {String(badgeCount)}
          </span>
        )}
      </span>
    </button>
  );
}

function MobilePeopleDirectory({
  contacts,
  activeContactId,
  displayName,
  isLocalMock,
  onSelectContact,
  onOpenNewContact,
}: {
  readonly contacts: readonly ContactResponse[];
  readonly activeContactId: string | null;
  readonly displayName: string;
  readonly isLocalMock: boolean;
  readonly onSelectContact: (contactId: string) => void;
  readonly onOpenNewContact: () => void;
}): JSX.Element {
  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-[#23170F]">Counterparts</h1>
        <button
          id="btn-people-add-contact"
          type="button"
          onClick={onOpenNewContact}
          className="md-btn md-btn-filled"
        >
          + New Counterpart
        </button>
      </div>

      {contacts.length === 0 ? (
        <EmptyStateCard
          title="No counterparts yet"
          description="Add a counterpart to prepare a tailored meeting brief."
          actionLabel="New Counterpart"
          onAction={onOpenNewContact}
        />
      ) : (
        <ul className="space-y-3">
          {contacts.map((contact) => {
            const selected = contact.id === activeContactId;
            return (
              <li key={contact.id}>
                <button
                  type="button"
                  onClick={() => onSelectContact(contact.id)}
                  className={`md-card flex w-full items-center justify-between gap-3 p-4 text-left ${
                    selected ? "border-[#4A2E1B] bg-[#F5EEE4]" : ""
                  }`}
                >
                  <div className="min-w-0">
                    <p className="truncate text-base font-semibold text-[#23170F]">
                      {contact.name}
                    </p>
                    {(contact.title || contact.organization) && (
                      <p className="truncate text-xs text-[#594638]">
                        {[contact.title, contact.organization].filter(Boolean).join(" · ")}
                      </p>
                    )}
                  </div>
                  <span className="text-xs font-semibold text-[#4A2E1B]">
                    {selected ? "Active" : "Open"}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="md-card-tonal p-4 text-xs text-[#594638]">
        Signed in as <strong className="text-[#23170F]">{displayName}</strong> (
        {isLocalMock ? "Local test mode" : "Verified identity"}).
      </div>
    </section>
  );
}
