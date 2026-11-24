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
import {
  loadStoredCalendarEvents,
  saveStoredCalendarEvents,
} from "./calendar/calendarStore";
import type { CalendarCoffeeChatEvent } from "./calendar/calendarTypes";
import {
  fetchReadOnlyGoogleCalendarEvents,
  requestGoogleCalendarReadOnlyToken,
} from "./calendar/googleCalendarClient";
import { parseIcsCalendarEvents } from "./calendar/icsParser";
import { AuthSignInGate } from "./components/AuthSignInGate";
import { ContactFormModal } from "./components/ContactFormModal";
import { errorToFeedbackNotice } from "./components/formatters";
import { ClubhouseScreen } from "./components/screens/ClubhouseScreen";
import { CueStudioScreen } from "./components/screens/CueStudioScreen";
import { DebriefKeepsakesScreen } from "./components/screens/DebriefKeepsakesScreen";
import { PocketCueCardsScreen } from "./components/screens/PocketCueCardsScreen";
import {
  QuickSparkSetupScreen,
  type QuickSparkSetupInitialSeed,
} from "./components/screens/QuickSparkSetupScreen";
import { RelationshipJournalScreen } from "./components/screens/RelationshipJournalScreen";
import { FocusedTopBar } from "./components/shell/FocusedTopBar";
import { MobileDock } from "./components/shell/MobileDock";
import { TopBarShell, type MainSpace } from "./components/shell/TopBarShell";
import { StatusBanner } from "./components/StatusFeedback";
import {
  loadCoachingDefaults,
  saveCoachingDefaults,
  type CoachingStyleDefaults,
} from "./state/coachingDefaultsStore";
import {
  loadStarredQuestionIds,
  saveStarredQuestionIds,
  toggleQuestionStar,
} from "./state/starredQuestionsStore";

type HealthViewState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly data: HealthPayload }
  | { readonly kind: "error"; readonly message: string };

type ActiveRouteView =
  | { readonly kind: "space"; readonly space: MainSpace; readonly journalMode?: "contact" | "coaching_style" }
  | { readonly kind: "setup"; readonly returnSpace: MainSpace; readonly seed: QuickSparkSetupInitialSeed | null }
  | { readonly kind: "pocket" }
  | {
      readonly kind: "debrief";
      readonly returnSpace: MainSpace;
      readonly calendarEvent: CalendarCoffeeChatEvent | null;
    };

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

  const [routeView, setRouteView] = useState<ActiveRouteView>({
    kind: "space",
    space: "clubhouse",
  });
  const [isContactModalOpen, setIsContactModalOpen] = useState(false);

  const [contacts, setContacts] = useState<readonly ContactResponse[]>([]);
  const [activeContactId, setActiveContactId] = useState<string | null>(null);
  const [meetings, setMeetings] = useState<readonly MeetingResponse[]>([]);
  const [meetingsByContact, setMeetingsByContact] = useState<
    ReadonlyMap<string, readonly MeetingResponse[]>
  >(new Map());
  const [activeBrief, setActiveBrief] = useState<PreparationBriefResponse | null>(null);
  const [briefRevisions, setBriefRevisions] = useState<readonly PreparationBriefResponse[]>([]);
  const [pendingProposals, setPendingProposals] = useState<readonly MemoryProposalResponse[]>([]);
  const [memories, setMemories] = useState<readonly MemoryResponse[]>([]);
  const [includeSuperseded, setIncludeSuperseded] = useState(false);

  const [calendarEvents, setCalendarEvents] = useState<readonly CalendarCoffeeChatEvent[]>([]);
  const [calendarSyncing, setCalendarSyncing] = useState(false);
  const [calendarNotice, setCalendarNotice] = useState<string | null>(null);

  const [starredQuestionIds, setStarredQuestionIds] = useState<ReadonlySet<string>>(new Set());

  const currentUserId = session?.principal.user_id ?? null;
  const currentDisplayName =
    session?.principal.display_name ?? session?.principal.user_id ?? "Guest";
  const isLocalMock = session?.principal.auth_provider === "local_mock";

  const [styleDefaults, setStyleDefaults] = useState<CoachingStyleDefaults>(() =>
    loadCoachingDefaults(currentUserId),
  );

  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  const sessionRef = useRef<StoredAuthSession | null>(session);
  sessionRef.current = session;

  const authConfigRef = useRef<AuthClientConfigResponse | null>(authConfig);
  authConfigRef.current = authConfig;

  useEffect(() => {
    setStyleDefaults(loadCoachingDefaults(currentUserId));
    if (currentUserId) {
      setCalendarEvents(
        loadStoredCalendarEvents(currentUserId, {
          isLocalMock,
          userDisplayName: currentDisplayName,
        }),
      );
    } else {
      setCalendarEvents([]);
    }
  }, [currentDisplayName, currentUserId, isLocalMock]);

  // Sync starred cue cards whenever the active brief changes
  useEffect(() => {
    if (!activeBrief) {
      setStarredQuestionIds(new Set());
      return;
    }
    const allIds = activeBrief.suggested_questions.map((q) => q.id);
    setStarredQuestionIds(loadStarredQuestionIds(currentUserId, activeBrief.id, allIds));
  }, [activeBrief, currentUserId]);

  // Keep document title synchronized with active v2 view (zero em-dashes)
  useEffect(() => {
    if (!session) {
      document.title = "brew. · Thoughtful Coffee Chat & Relationship Companion";
      return;
    }
    if (routeView.kind === "setup") {
      document.title = "brew. · Shape Conversation";
    } else if (routeView.kind === "pocket") {
      document.title = "brew. · Pocket Cue Cards";
    } else if (routeView.kind === "debrief") {
      document.title = "brew. · Post-Chat Debrief";
    } else if (routeView.space === "studio") {
      document.title = "brew. · Cue Studio";
    } else if (routeView.space === "journal") {
      document.title = "brew. · Relationship Journal";
    } else {
      document.title = "brew. · Clubhouse";
    }
  }, [routeView, session]);

  const resetAuthenticatedState = useCallback((expiredReason: string | null): void => {
    clearStoredSession();
    sessionRef.current = null;
    setSession(null);
    setContacts([]);
    setActiveContactId(null);
    setMeetings([]);
    setMeetingsByContact(new Map());
    setActiveBrief(null);
    setBriefRevisions([]);
    setPendingProposals([]);
    setMemories([]);
    setRouteView({ kind: "space", space: "clubhouse" });
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
      const allIds = brief.suggested_questions.map((q) => q.id);
      setStarredQuestionIds(
        loadStarredQuestionIds(sessionRef.current?.principal.user_id ?? null, brief.id, allIds),
      );
      setActiveBrief(brief);
      setBriefRevisions(revisionsResp.items);
    },
    [apiClient],
  );

  const loadContactContext = useCallback(
    async (contactId: string, explicitBriefId?: string | null): Promise<void> => {
      setLoadingWorkspace(true);
      setWorkspaceError(null);
      try {
        const meetingsResp = await apiClient.listMeetings(contactId);
        setMeetings(meetingsResp.items);
        setMeetingsByContact((prev) => {
          const next = new Map(prev);
          next.set(contactId, meetingsResp.items);
          return next;
        });

        const targetBriefId =
          explicitBriefId ??
          meetingsResp.items.find(
            (m) => typeof m.latest_brief_id === "string" && m.latest_brief_id.length > 0,
          )?.latest_brief_id ??
          null;

        if (targetBriefId) {
          await loadBriefWithRevisions(targetBriefId);
        } else {
          setActiveBrief(null);
          setBriefRevisions([]);
        }
      } catch (err: unknown) {
        if (!(err instanceof BrewApiError && err.isUnauthorized)) {
          setWorkspaceError(
            errorToFeedbackNotice(err, "Failed to load contact session").message ?? null,
          );
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
    async (contactId: string, explicitBriefId?: string | null): Promise<void> => {
      setActiveContactId(contactId);
      await loadContactContext(contactId, explicitBriefId);
    },
    [loadContactContext],
  );

  const handleCreateContact = useCallback(
    async (payload: CreateContactRequest): Promise<ContactResponse> => {
      const created = await apiClient.createContact(payload);
      setContacts((prev) => [created, ...prev]);
      setActiveContactId(created.id);
      setMeetings([]);
      setMeetingsByContact((prev) => {
        const next = new Map(prev);
        next.set(created.id, []);
        return next;
      });
      setActiveBrief(null);
      setBriefRevisions([]);
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
      setActiveContactId(payload.contact_id);
      setMeetings(meetingsResp.items);
      setMeetingsByContact((prev) => {
        const next = new Map(prev);
        next.set(payload.contact_id, meetingsResp.items);
        return next;
      });
      const allIds = created.suggested_questions.map((q) => q.id);
      setStarredQuestionIds(
        loadStarredQuestionIds(sessionRef.current?.principal.user_id ?? null, created.id, allIds),
      );
      setActiveBrief(created);
      setBriefRevisions(revisionsResp.items);
      setRouteView({ kind: "space", space: "studio" });
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
        setMeetingsByContact((prev) => {
          const next = new Map(prev);
          next.set(activeContactId, meetingsResp.items);
          return next;
        });
      }
      return updated;
    },
    [activeContactId, apiClient],
  );

  const handleToggleStarQuestion = useCallback(
    (questionId: string): void => {
      if (!activeBrief) {
        return;
      }
      setStarredQuestionIds((prev) => {
        const next = toggleQuestionStar(prev, questionId);
        saveStarredQuestionIds(currentUserId, activeBrief.id, next);
        return next;
      });
    },
    [activeBrief, currentUserId],
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
          setWorkspaceError(errorToFeedbackNotice(err, "Could not load keepsakes").message ?? null);
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

  const handleSaveStyleDefaults = useCallback(
    (next: CoachingStyleDefaults): void => {
      setStyleDefaults(next);
      if (currentUserId) {
        saveCoachingDefaults(currentUserId, next);
      }
    },
    [currentUserId],
  );

  const handleConnectGoogleCalendar = useCallback(async (): Promise<void> => {
    const clientId = authConfig?.google_oauth_client_id;
    if (!clientId) {
      return;
    }
    setCalendarSyncing(true);
    setCalendarNotice(null);
    try {
      const calToken = await requestGoogleCalendarReadOnlyToken(clientId);
      const events = await fetchReadOnlyGoogleCalendarEvents(calToken, {
        selfDisplayName: currentDisplayName,
      });
      setCalendarEvents(events);
      saveStoredCalendarEvents(currentUserId, events);
      setCalendarNotice(`Synced ${String(events.length)} coffee chat events from Google Calendar.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Could not sync Google Calendar.";
      setWorkspaceError(msg);
    } finally {
      setCalendarSyncing(false);
    }
  }, [authConfig?.google_oauth_client_id, currentDisplayName, currentUserId]);

  const handleImportIcsText = useCallback(
    (icsText: string): void => {
      const parsed = parseIcsCalendarEvents(icsText, {
        selfDisplayName: currentDisplayName,
        source: "gcal",
      });
      if (parsed.length === 0) {
        setCalendarNotice(
          "No matching coffee chat events found in the pasted .ics text (include Coffee Chat, 1:1, or #brew in the title).",
        );
        return;
      }
      setCalendarEvents((prev) => {
        const byId = new Map<string, CalendarCoffeeChatEvent>(prev.map((ev) => [ev.id, ev]));
        for (const ev of parsed) {
          byId.set(ev.id, ev);
        }
        const merged = Array.from(byId.values()).sort(
          (a, b) => Date.parse(a.scheduledStartIso) - Date.parse(b.scheduledStartIso),
        );
        saveStoredCalendarEvents(currentUserId, merged);
        return merged;
      });
      setCalendarNotice(`Imported ${String(parsed.length)} calendar chat slot(s).`);
    },
    [currentDisplayName, currentUserId],
  );

  const handleClearCalendarEvents = useCallback((): void => {
    setCalendarEvents([]);
    saveStoredCalendarEvents(currentUserId, []);
    setCalendarNotice("Cleared calendar slots.");
  }, [currentUserId]);

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

  const currentMainSpace: MainSpace =
    routeView.kind === "space" ? routeView.space : "clubhouse";

  const isBrowsingSpace = routeView.kind === "space" && !isContactModalOpen;

  const openSetupWithSeed = (seed: QuickSparkSetupInitialSeed | null): void => {
    setRouteView({
      kind: "setup",
      returnSpace: currentMainSpace,
      seed,
    });
  };

  return (
    <div className="min-h-screen bg-brew-bg text-brew-plum">
      <a href="#main-workspace" className="brew-skip-link">
        Skip to workspace
      </a>

      {/* Contextual v2 Top Shell */}
      {routeView.kind === "space" && (
        <TopBarShell
          activeSpace={routeView.space}
          onSelectSpace={(space) =>
            setRouteView({ kind: "space", space, journalMode: "contact" })
          }
          onOpenQuickSpark={() => openSetupWithSeed(null)}
          onOpenCoachingStyle={() =>
            setRouteView({
              kind: "space",
              space: "journal",
              journalMode: "coaching_style",
            })
          }
          userDisplayName={currentDisplayName}
          pendingProposalsCount={pendingProposals.length}
        />
      )}

      {routeView.kind === "setup" && (
        <FocusedTopBar
          backLabel="Back to Clubhouse"
          backId="btn-setup-back"
          onBack={() => setRouteView({ kind: "space", space: routeView.returnSpace })}
          onLogoClick={() => setRouteView({ kind: "space", space: "clubhouse" })}
          userDisplayName={currentDisplayName}
          onAvatarClick={() =>
            setRouteView({
              kind: "space",
              space: "journal",
              journalMode: "coaching_style",
            })
          }
        />
      )}

      {routeView.kind === "pocket" && (
        <FocusedTopBar
          backLabel="Full Studio"
          backId="btn-pocket-back"
          centerEyebrow="POCKET CUE CARDS"
          onBack={() => setRouteView({ kind: "space", space: "studio" })}
          rightAction={{
            label: "Debrief",
            id: "btn-pocket-open-debrief",
            onClick: () =>
              setRouteView({
                kind: "debrief",
                returnSpace: "studio",
                calendarEvent: null,
              }),
          }}
        />
      )}

      {routeView.kind === "debrief" && (
        <FocusedTopBar
          backLabel="Back to Clubhouse"
          mobileBackLabel="Done"
          backId="btn-debrief-back"
          mobileCenterEyebrow="DEBRIEF"
          hideMobileAvatar
          onBack={() => setRouteView({ kind: "space", space: routeView.returnSpace })}
          onLogoClick={() => setRouteView({ kind: "space", space: "clubhouse" })}
          userDisplayName={currentDisplayName}
          onAvatarClick={() =>
            setRouteView({
              kind: "space",
              space: "journal",
              journalMode: "coaching_style",
            })
          }
        />
      )}

      <main
        id="main-workspace"
        className={`mx-auto max-w-[1368px] px-5 pt-3 md:px-9 md:pt-[26px] ${
          isBrowsingSpace ? "pb-28 md:pb-12" : "pb-14"
        }`}
      >
        <div className="space-y-5">
          {workspaceError && (
            <StatusBanner
              notice={{
                kind: "error",
                title: "Workspace notice",
                message: workspaceError,
              }}
              onDismiss={() => setWorkspaceError(null)}
            />
          )}

          {routeView.kind === "space" && routeView.space === "clubhouse" && (
            <ClubhouseScreen
              userDisplayName={currentDisplayName}
              contacts={contacts}
              activeContact={activeContact}
              meetings={meetings}
              activeBrief={activeBrief}
              pendingProposals={pendingProposals}
              memories={memories}
              calendarEvents={calendarEvents}
              loadingWorkspace={loadingWorkspace}
              googleCalendarAvailable={Boolean(authConfig?.google_oauth_client_id)}
              calendarSyncing={calendarSyncing}
              calendarNotice={calendarNotice}
              onOpenCueStudio={(contactId, briefId) => {
                if (contactId && contactId !== activeContactId) {
                  void handleSelectContact(contactId, briefId ?? null);
                } else if (briefId && briefId !== activeBrief?.id) {
                  void loadBriefWithRevisions(briefId);
                }
                setRouteView({ kind: "space", space: "studio" });
              }}
              onOpenPocketMode={(contactId, briefId) => {
                if (contactId && contactId !== activeContactId) {
                  void handleSelectContact(contactId, briefId ?? null);
                } else if (briefId && briefId !== activeBrief?.id) {
                  void loadBriefWithRevisions(briefId);
                }
                setRouteView({ kind: "pocket" });
              }}
              onOpenSetupWithCalendarEvent={(calEv) =>
                openSetupWithSeed({ calendarEvent: calEv })
              }
              onOpenSetupWithSparkText={(sparkText) =>
                openSetupWithSeed({ sparkText })
              }
              onOpenSetupForContact={(contactId) =>
                openSetupWithSeed({ contactId })
              }
              onOpenNewContactModal={() => setIsContactModalOpen(true)}
              onOpenDebrief={(opts) => {
                if (opts?.contactId && opts.contactId !== activeContactId) {
                  void handleSelectContact(opts.contactId);
                }
                setRouteView({
                  kind: "debrief",
                  returnSpace: "clubhouse",
                  calendarEvent: opts?.calendarEvent ?? null,
                });
              }}
              onOpenJournalFolio={(contactId) => {
                void handleSelectContact(contactId);
                setRouteView({
                  kind: "space",
                  space: "journal",
                  journalMode: "contact",
                });
              }}
              onApproveProposal={handleApproveProposal}
              onConnectGoogleCalendar={handleConnectGoogleCalendar}
              onImportIcsText={handleImportIcsText}
            />
          )}

          {routeView.kind === "space" && routeView.space === "studio" && (
            <CueStudioScreen
              contacts={contacts}
              activeContact={activeContact}
              meetings={meetings}
              activeBrief={activeBrief}
              briefRevisions={briefRevisions}
              memories={memories}
              calendarEvents={calendarEvents}
              starredQuestionIds={starredQuestionIds}
              styleDefaults={styleDefaults}
              loadingWorkspace={loadingWorkspace}
              onToggleStarQuestion={handleToggleStarQuestion}
              onSelectContact={(contactId) => handleSelectContact(contactId)}
              onOpenSetup={(contactId) => openSetupWithSeed({ contactId: contactId ?? null })}
              onOpenPocketGlance={() => setRouteView({ kind: "pocket" })}
              onOpenDebrief={(contactId) => {
                if (contactId && contactId !== activeContactId) {
                  void handleSelectContact(contactId);
                }
                setRouteView({
                  kind: "debrief",
                  returnSpace: "studio",
                  calendarEvent: null,
                });
              }}
              onReviseBrief={handleReviseBrief}
              onReloadBrief={loadBriefWithRevisions}
            />
          )}

          {routeView.kind === "space" && routeView.space === "journal" && (
            <RelationshipJournalScreen
              userDisplayName={currentDisplayName}
              userId={session.principal.user_id}
              isLocalMock={isLocalMock}
              contacts={contacts}
              activeContactId={activeContactId}
              meetingsByContact={meetingsByContact}
              activeBrief={activeBrief}
              pendingProposals={pendingProposals}
              memories={memories}
              calendarEvents={calendarEvents}
              includeSuperseded={includeSuperseded}
              initialFolioMode={routeView.journalMode ?? "contact"}
              styleDefaults={styleDefaults}
              health={healthState}
              googleCalendarAvailable={Boolean(authConfig?.google_oauth_client_id)}
              calendarSyncing={calendarSyncing}
              onSelectContactFolio={(contactId) => handleSelectContact(contactId)}
              onOpenNewContactModal={() => setIsContactModalOpen(true)}
              onOpenCueStudioForContact={(contactId, briefId) => {
                void handleSelectContact(contactId, briefId ?? null);
                setRouteView({ kind: "space", space: "studio" });
              }}
              onOpenSetupForContact={(contactId) => openSetupWithSeed({ contactId })}
              onOpenDebrief={(contactId) => {
                if (contactId && contactId !== activeContactId) {
                  void handleSelectContact(contactId);
                }
                setRouteView({
                  kind: "debrief",
                  returnSpace: "journal",
                  calendarEvent: null,
                });
              }}
              onToggleIncludeSuperseded={(next) => {
                void handleToggleIncludeSuperseded(next);
              }}
              onUpdateMemory={handleUpdateMemory}
              onDeleteMemory={handleDeleteMemory}
              onSaveStyleDefaults={handleSaveStyleDefaults}
              onConnectGoogleCalendar={handleConnectGoogleCalendar}
              onImportIcsText={handleImportIcsText}
              onClearCalendarEvents={handleClearCalendarEvents}
              onRefreshHealth={() => {
                void refreshRuntimeBootstrap();
              }}
              onSignOut={() => {
                void handleSignOut();
              }}
            />
          )}

          {routeView.kind === "setup" && (
            <QuickSparkSetupScreen
              contacts={contacts}
              calendarEvents={calendarEvents}
              styleDefaults={styleDefaults}
              initialSeed={routeView.seed}
              onCreateContact={handleCreateContact}
              onGenerateBrief={handleGenerateBrief}
              onOpenNewContactModal={() => setIsContactModalOpen(true)}
            />
          )}

          {routeView.kind === "pocket" && (
            <PocketCueCardsScreen
              activeContact={activeContact}
              activeBrief={activeBrief}
              calendarEvents={calendarEvents}
              starredQuestionIds={starredQuestionIds}
              onBackToStudio={() => setRouteView({ kind: "space", space: "studio" })}
              onReviseBrief={handleReviseBrief}
            />
          )}

          {routeView.kind === "debrief" && (
            <DebriefKeepsakesScreen
              contacts={contacts}
              activeContact={activeContact}
              activeMeeting={activeMeeting}
              activeBrief={activeBrief}
              targetCalendarEvent={routeView.calendarEvent}
              pendingProposals={pendingProposals}
              memories={memories}
              onSelectContact={(contactId) => handleSelectContact(contactId)}
              onCreateContact={handleCreateContact}
              onProposeMemories={handleProposeMemories}
              onApproveProposal={handleApproveProposal}
              onRejectProposal={handleRejectProposal}
            />
          )}
        </div>
      </main>

      {isBrowsingSpace && (
        <MobileDock
          activeSpace={currentMainSpace}
          onSelectSpace={(space) =>
            setRouteView({ kind: "space", space, journalMode: "contact" })
          }
          onOpenQuickSpark={() => openSetupWithSeed(null)}
          pendingProposalsCount={pendingProposals.length}
        />
      )}

      <ContactFormModal
        isOpen={isContactModalOpen}
        onClose={() => setIsContactModalOpen(false)}
        onCreateContact={async (payload) => {
          const created = await handleCreateContact(payload);
          if (routeView.kind === "space" && routeView.space === "clubhouse") {
            openSetupWithSeed({ contactId: created.id });
          } else if (routeView.kind === "space" && routeView.space === "journal") {
            setRouteView({ kind: "space", space: "journal", journalMode: "contact" });
          }
          return created;
        }}
      />
    </div>
  );
}
