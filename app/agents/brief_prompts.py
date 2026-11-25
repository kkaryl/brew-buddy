"""Prompt builders and the JSON output contract text for the brief specialists."""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.domain.briefs.context import BriefPreparationContext
from app.domain.briefs.models import PreparationBrief
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingTone

BRIEF_WORKFLOW_JSON_CONTRACT = """

## Structured Brief Workflow Output Contract
You are executing inside Brew's automated Meeting Preparation Workflow.
1. `contact`, `user_preferences`, `approved_preference_memories`, and `approved_contact_memories`
   are ALREADY pre-loaded in the `BASELINE_GROUNDING_CONTEXT` JSON in this prompt; do NOT re-call
   `get_user_preferences` or `get_contact_context` when that context is already provided. Only call
   `get_meeting_history` if checking prior sessions for a returning contact is genuinely needed.
2. If any tool returns `status="error"`, do NOT loop retries endlessly and NEVER invent missing
   history or biographical details.
3. Never use em-dashes in any generated text field (`contact_context`, `meeting_objective`,
   `conversation_openers`, `time_boxed_agenda`, `suggested_questions`,
   `suggested_follow_up_topics`, or `revision_summary`). Use periods, commas, colons, or middle
   dots instead.
4. Return ONLY a single valid JSON object (no markdown commentary outside JSON) conforming to:
   - `contact_context` (string, 3-2000 chars): Grounded counterpart summary using ONLY verified
     facts from the contact profile, retrieved memories, and meeting input. Never invent degrees,
     past employers, tenure, publications, or private characteristics.
   - `meeting_objective` (string, 3-500 chars): Concrete goal for this session.
   - `conversation_openers` (array of 2 to 3 strings): Tailored openers matching the target tone.
   - `time_boxed_agenda` (array of 2 to 6 objects `{title, duration_minutes, description}`):
     Realistic segments whose `duration_minutes` sum STRICTLY to the target `duration_minutes`.
   - `suggested_questions` (array of 5 to 8 objects `{id, question, rationale, category}`, unless
     an explicit `preferred_question_count` is specified): Prioritized, non-redundant open-ended
     questions whose `rationale` explains how each question advances the meeting goal.
   - `suggested_follow_up_topics` (array of 1 to 6 strings): Concrete follow-up threads.
   - `referenced_memory_ids` (array of strings): ONLY memory IDs present in approved context.
   - `revision_summary` (string or null): Null on initial generation; concise summary of applied
     changes on brief refinement.
"""


def _format_baseline_context_payload(context: BriefPreparationContext) -> dict[str, object]:
    """Serialize verified pre-brief context as untrusted structured data for grounding."""
    prefs = context.user_preferences
    return {
        "data_trust_level": "untrusted_user_data",
        "contact": {
            "id": context.contact.id,
            "name": context.contact.name,
            "title": context.contact.title,
            "role": context.contact.role,
            "organization": context.contact.organization,
            "context_notes": context.contact.context_notes,
        },
        "user_preferences": (
            {
                "default_tone": prefs.default_tone.value,
                "default_duration_minutes": prefs.default_duration_minutes,
                "preferred_question_count": prefs.preferred_question_count,
                "communication_style_notes": prefs.communication_style_notes,
                "focus_areas": list(prefs.focus_areas),
            }
            if prefs is not None
            else None
        ),
        "approved_preference_memories": [
            {
                "memory_id": item.memory_id,
                "type": item.memory_type.value,
                "epistemic_status": item.epistemic_status.value,
                "source_type": item.source.source_type.value,
                "recorded_at_utc": item.source.recorded_at.isoformat(),
                "text": item.text,
            }
            for item in context.preference_memories
        ],
        "approved_contact_memories": [
            {
                "memory_id": item.memory_id,
                "type": item.memory_type.value,
                "epistemic_status": item.epistemic_status.value,
                "source_type": item.source.source_type.value,
                "meeting_id": item.source.meeting_id,
                "recorded_at_utc": item.source.recorded_at.isoformat(),
                "text": item.text,
            }
            for item in context.contact_memories
        ],
        "recent_meetings": [
            {
                "meeting_id": item.meeting_id,
                "purpose": item.purpose.value,
                "objective": item.objective,
                "duration_minutes": item.duration_minutes,
                "notes_excerpt": item.notes_excerpt,
            }
            for item in context.recent_meetings
        ],
        "allowed_referenced_memory_ids": context.referenced_memory_ids,
    }


def build_generation_prompt(
    *,
    meeting: Meeting,
    context: BriefPreparationContext,
    corrective_feedback: Sequence[str] | None,
) -> str:
    target_q_desc = (
        f"exactly {context.user_preferences.preferred_question_count}"
        if context.user_preferences is not None
        else "5 to 8"
    )
    payload = {
        "workflow_task": "generate_preparation_brief",
        "meeting": {
            "id": meeting.id,
            "contact_id": meeting.contact_id,
            "purpose": meeting.purpose.value,
            "tone": meeting.tone.value,
            "objective": meeting.objective,
            "duration_minutes": meeting.duration_minutes,
            "notes": meeting.notes,
        },
        "quality_requirements": {
            "openers": "2 to 3 tailored openers",
            "questions": f"{target_q_desc} non-redundant questions with goal-linked rationales",
            "agenda_total_minutes": meeting.duration_minutes,
        },
        "verified_baseline_context": _format_baseline_context_payload(context),
    }
    prompt = (
        "Synthesize an initial meeting preparation brief in strict JSON format.\n"
        f"REQUEST_PAYLOAD_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    if corrective_feedback:
        joined = "\n".join(f"- {item}" for item in corrective_feedback)
        prompt += (
            "\n\n[CORRECTIVE REGENERATION REQUIRED — FIX ALL VIOLATIONS]\n"
            "Your previous candidate brief failed validation. Regenerate a complete valid JSON "
            f"brief fixing every item below:\n{joined}"
        )
    return prompt


def build_refinement_prompt(
    *,
    current_brief: PreparationBrief,
    meeting: Meeting,
    context: BriefPreparationContext,
    instructions: str,
    target_duration_minutes: int,
    target_tone: MeetingTone,
    corrective_feedback: Sequence[str] | None,
) -> str:
    payload = {
        "workflow_task": "refine_preparation_brief",
        "refinement_instructions": instructions,
        "target_duration_minutes": target_duration_minutes,
        "target_tone": target_tone.value,
        "current_brief_version": current_brief.version,
        "current_brief": {
            "contact_context": current_brief.contact_context,
            "meeting_objective": current_brief.meeting_objective,
            "conversation_openers": list(current_brief.conversation_openers),
            "time_boxed_agenda": [
                item.model_dump(mode="json") for item in current_brief.time_boxed_agenda
            ],
            "suggested_questions": [
                item.model_dump(mode="json") for item in current_brief.suggested_questions
            ],
            "suggested_follow_up_topics": list(current_brief.suggested_follow_up_topics),
            "referenced_memory_ids": list(current_brief.referenced_memory_ids),
        },
        "meeting": {
            "id": meeting.id,
            "contact_id": meeting.contact_id,
            "purpose": meeting.purpose.value,
            "objective": meeting.objective,
        },
        "verified_baseline_context": _format_baseline_context_payload(context),
    }
    prompt = (
        "Refine the existing preparation brief according to `refinement_instructions`, "
        "preserving unchanged context sensibly and adapting the agenda strictly to "
        "`target_duration_minutes` and `target_tone`.\n"
        f"REFINEMENT_PAYLOAD_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    if corrective_feedback:
        joined = "\n".join(f"- {item}" for item in corrective_feedback)
        prompt += (
            "\n\n[CORRECTIVE REGENERATION REQUIRED — FIX ALL VIOLATIONS]\n"
            "Your previous refined brief failed validation. Regenerate a complete valid JSON "
            f"brief fixing every item below:\n{joined}"
        )
    return prompt
