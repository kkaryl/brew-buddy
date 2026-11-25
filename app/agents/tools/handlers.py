"""One handler per conversation_coach tool."""

from __future__ import annotations

import asyncio
from typing import cast

from google.adk.tools.tool_context import ToolContext

from app.agents.tools.contracts import (
    ContactContextDataOutput,
    GetContactContextInput,
    GetContactContextOutput,
    GetContactContextResponseDict,
    GetMeetingHistoryInput,
    GetMeetingHistoryOutput,
    GetMeetingHistoryResponseDict,
    GetUserPreferencesInput,
    GetUserPreferencesOutput,
    GetUserPreferencesResponseDict,
    MeetingHistoryDataOutput,
    MeetingHistoryItemOutput,
    MemorySummaryOutput,
    SuggestedMemoryCandidateOutput,
    SuggestMemoryCandidatesDataOutput,
    SuggestMemoryCandidatesInput,
    SuggestMemoryCandidatesOutput,
    SuggestMemoryCandidatesResponseDict,
    ToolStatus,
    UserPreferencesDataOutput,
)
from app.agents.tools.dependencies import CoachingToolDependencies
from app.agents.tools.errors import resolve_authenticated_principal, translate_tool_exception
from app.agents.tools.telemetry import record_tool_failure_telemetry, tool_telemetry_scope
from app.application.shared.telemetry import ATTR_MEMORY_RETRIEVED_COUNT, ATTR_MEMORY_SAVED_COUNT
from app.domain.meetings.types import MeetingPurpose
from app.domain.memory.types import MemorySourceType


async def execute_get_user_preferences(
    *,
    max_preference_memories: int,
    tool_context: ToolContext | None,
    deps: CoachingToolDependencies,
) -> GetUserPreferencesResponseDict:
    with tool_telemetry_scope("get_user_preferences") as tracker:
        try:
            principal = resolve_authenticated_principal(tool_context)
            validated_in = GetUserPreferencesInput(
                max_preference_memories=max_preference_memories,
            )
            projection = await asyncio.wait_for(
                deps.service.get_user_preferences(
                    principal=principal,
                    max_preference_memories=validated_in.max_preference_memories,
                ),
                timeout=deps.io_timeout_seconds,
            )
            mem_count = len(projection.approved_preference_memories)
            is_empty = not projection.has_saved_preferences and mem_count == 0
            status: ToolStatus = "empty" if is_empty else "success"
            tracker.status = status
            tracker.set_attribute(ATTR_MEMORY_RETRIEVED_COUNT, mem_count)
            output = GetUserPreferencesOutput(
                status=status,
                data=UserPreferencesDataOutput(
                    has_saved_preferences=projection.has_saved_preferences,
                    default_tone=projection.default_tone,
                    default_duration_minutes=projection.default_duration_minutes,
                    preferred_question_count=projection.preferred_question_count,
                    communication_style_notes=projection.communication_style_notes,
                    focus_areas=projection.focus_areas,
                    approved_preference_memories=[
                        MemorySummaryOutput(
                            memory_id=item.memory_id,
                            memory_type=item.memory_type,
                            text=item.text,
                        )
                        for item in projection.approved_preference_memories
                    ],
                    was_truncated=projection.was_truncated,
                    injection_detected=projection.injection_detected,
                ),
            )
            return cast(GetUserPreferencesResponseDict, output.model_dump(mode="json"))
        except Exception as exc:
            err = translate_tool_exception("get_user_preferences", exc)
            record_tool_failure_telemetry(
                tracker,
                tool_name="get_user_preferences",
                err=err,
                exc=exc,
            )
            failed = GetUserPreferencesOutput(status="error", data=None, error=err)
            return cast(GetUserPreferencesResponseDict, failed.model_dump(mode="json"))


async def execute_get_contact_context(
    *,
    contact_id: str,
    meeting_objective: str | None,
    max_memories: int,
    tool_context: ToolContext | None,
    deps: CoachingToolDependencies,
) -> GetContactContextResponseDict:
    with tool_telemetry_scope("get_contact_context") as tracker:
        try:
            principal = resolve_authenticated_principal(tool_context)
            validated_in = GetContactContextInput(
                contact_id=contact_id,
                meeting_objective=meeting_objective,
                max_memories=max_memories,
            )
            projection = await asyncio.wait_for(
                deps.service.get_contact_context(
                    principal=principal,
                    contact_id=validated_in.contact_id,
                    meeting_objective=validated_in.meeting_objective,
                    max_memories=validated_in.max_memories,
                ),
                timeout=deps.io_timeout_seconds,
            )
            mem_count = len(projection.approved_memories)
            status: ToolStatus = "success" if projection.has_prior_context else "empty"
            tracker.status = status
            tracker.set_attribute(ATTR_MEMORY_RETRIEVED_COUNT, mem_count)
            output = GetContactContextOutput(
                status=status,
                data=ContactContextDataOutput(
                    contact_id=projection.contact_id,
                    name=projection.name,
                    title=projection.title,
                    role=projection.role,
                    organization=projection.organization,
                    context_notes=projection.context_notes,
                    approved_memories=[
                        MemorySummaryOutput(
                            memory_id=item.memory_id,
                            memory_type=item.memory_type,
                            text=item.text,
                        )
                        for item in projection.approved_memories
                    ],
                    has_prior_context=projection.has_prior_context,
                    was_truncated=projection.was_truncated,
                    injection_detected=projection.injection_detected,
                ),
            )
            return cast(GetContactContextResponseDict, output.model_dump(mode="json"))
        except Exception as exc:
            err = translate_tool_exception("get_contact_context", exc)
            record_tool_failure_telemetry(
                tracker,
                tool_name="get_contact_context",
                err=err,
                exc=exc,
            )
            failed = GetContactContextOutput(status="error", data=None, error=err)
            return cast(GetContactContextResponseDict, failed.model_dump(mode="json"))


async def execute_get_meeting_history(
    *,
    contact_id: str | None,
    purpose: MeetingPurpose | None,
    objective_hint: str | None,
    limit: int,
    tool_context: ToolContext | None,
    deps: CoachingToolDependencies,
) -> GetMeetingHistoryResponseDict:
    with tool_telemetry_scope("get_meeting_history") as tracker:
        try:
            principal = resolve_authenticated_principal(tool_context)
            validated_in = GetMeetingHistoryInput(
                contact_id=contact_id,
                purpose=purpose,
                objective_hint=objective_hint,
                limit=limit,
            )
            projection = await asyncio.wait_for(
                deps.service.get_meeting_history(
                    principal=principal,
                    contact_id=validated_in.contact_id,
                    purpose=validated_in.purpose,
                    objective_hint=validated_in.objective_hint,
                    limit=validated_in.limit,
                ),
                timeout=deps.io_timeout_seconds,
            )
            status: ToolStatus = "empty" if projection.total_returned == 0 else "success"
            tracker.status = status
            tracker.set_attribute("brew.meeting.retrieved_count", projection.total_returned)
            output = GetMeetingHistoryOutput(
                status=status,
                data=MeetingHistoryDataOutput(
                    meetings=[
                        MeetingHistoryItemOutput(
                            meeting_id=item.meeting_id,
                            contact_id=item.contact_id,
                            purpose=item.purpose,
                            tone=item.tone,
                            objective=item.objective,
                            duration_minutes=item.duration_minutes,
                            status=item.status,
                            scheduled_at_utc=item.scheduled_at_utc,
                            notes_excerpt=item.notes_excerpt,
                        )
                        for item in projection.meetings
                    ],
                    total_returned=projection.total_returned,
                    was_truncated=projection.was_truncated,
                    injection_detected=projection.injection_detected,
                ),
            )
            return cast(GetMeetingHistoryResponseDict, output.model_dump(mode="json"))
        except Exception as exc:
            err = translate_tool_exception("get_meeting_history", exc)
            record_tool_failure_telemetry(
                tracker,
                tool_name="get_meeting_history",
                err=err,
                exc=exc,
            )
            failed = GetMeetingHistoryOutput(status="error", data=None, error=err)
            return cast(GetMeetingHistoryResponseDict, failed.model_dump(mode="json"))


async def execute_suggest_memory_candidates(
    *,
    notes: str,
    contact_id: str | None,
    meeting_id: str | None,
    source_type: MemorySourceType,
    max_candidates: int,
    tool_context: ToolContext | None,
    deps: CoachingToolDependencies,
) -> SuggestMemoryCandidatesResponseDict:
    with tool_telemetry_scope("suggest_memory_candidates") as tracker:
        try:
            principal = resolve_authenticated_principal(tool_context)
            validated_in = SuggestMemoryCandidatesInput(
                notes=notes,
                contact_id=contact_id,
                meeting_id=meeting_id,
                source_type=source_type,
                max_candidates=max_candidates,
            )
            projection = await asyncio.wait_for(
                deps.service.suggest_memory_candidates(
                    principal=principal,
                    notes=validated_in.notes,
                    contact_id=validated_in.contact_id,
                    meeting_id=validated_in.meeting_id,
                    source_type=validated_in.source_type,
                    max_candidates=validated_in.max_candidates,
                ),
                timeout=deps.io_timeout_seconds,
            )
            status: ToolStatus = "empty" if projection.total_suggested == 0 else "success"
            tracker.status = status
            tracker.set_attribute(ATTR_MEMORY_SAVED_COUNT, projection.total_suggested)
            output = SuggestMemoryCandidatesOutput(
                status=status,
                data=SuggestMemoryCandidatesDataOutput(
                    candidates=[
                        SuggestedMemoryCandidateOutput(
                            proposal_id=item.proposal_id,
                            scope=item.scope,
                            contact_id=item.contact_id,
                            memory_type=item.memory_type,
                            text=item.text,
                            rationale=item.rationale,
                        )
                        for item in projection.candidates
                    ],
                    total_suggested=projection.total_suggested,
                    filtered_untrusted_directives=projection.filtered_untrusted_directives,
                ),
            )
            return cast(SuggestMemoryCandidatesResponseDict, output.model_dump(mode="json"))
        except Exception as exc:
            err = translate_tool_exception("suggest_memory_candidates", exc)
            record_tool_failure_telemetry(
                tracker,
                tool_name="suggest_memory_candidates",
                err=err,
                exc=exc,
            )
            failed = SuggestMemoryCandidatesOutput(status="error", data=None, error=err)
            return cast(SuggestMemoryCandidatesResponseDict, failed.model_dump(mode="json"))
