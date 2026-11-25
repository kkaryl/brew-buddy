"""Scripted deterministic brief coach agent standing in for the model."""

from __future__ import annotations

from collections.abc import Sequence

from app.application.shared.telemetry import brew_span
from app.domain.briefs.context import BriefPreparationContext
from app.domain.briefs.models import ConversationQuestion, PreparationBrief, TimeBoxedAgendaItem
from app.domain.briefs.ports import BriefAttemptMetrics, GeneratedBriefContent
from app.domain.briefs.quality.refinement import parse_refinement_overrides
from app.domain.meetings.models import Meeting
from app.domain.meetings.types import MeetingPurpose, MeetingTone
from app.domain.shared.types import MeetingDurationMinutes
from app.infrastructure.stubs.pii import scrub_basic_pii


def _build_time_boxed_agenda(
    *,
    duration_minutes: int,
    purpose: MeetingPurpose,
) -> list[TimeBoxedAgendaItem]:
    opening_minutes = max(1, duration_minutes // 5)
    closing_minutes = max(1, duration_minutes // 5)
    core_minutes = duration_minutes - opening_minutes - closing_minutes
    purpose_label = purpose.value.replace("_", " ")
    return [
        TimeBoxedAgendaItem(
            title="Rapport & Context Alignment",
            duration_minutes=opening_minutes,
            description=(
                f"Set a welcoming tone, reconnect on shared context, and confirm the "
                f"{duration_minutes}-minute timebox."
            ),
        ),
        TimeBoxedAgendaItem(
            title=f"Core {purpose_label.title()} Discussion",
            duration_minutes=core_minutes,
            description=(
                f"Explore prioritized questions aligned with the {purpose_label} objective "
                f"and listen for concrete examples."
            ),
        ),
        TimeBoxedAgendaItem(
            title="Synthesis & Next Steps",
            duration_minutes=closing_minutes,
            description=(
                "Summarize takeaways, confirm any agreed follow-ups, and express appreciation."
            ),
        ),
    ]


def _compose_contact_context(context: BriefPreparationContext) -> str:
    contact = context.contact
    descriptor_parts = [contact.name]
    if contact.title:
        descriptor_parts.append(contact.title)
    if contact.role and contact.role != contact.title:
        descriptor_parts.append(contact.role)
    if contact.organization:
        descriptor_parts.append(f"at {contact.organization}")

    summary = ", ".join(descriptor_parts) + "."
    if contact.context_notes:
        summary = f"{summary} Context: {contact.context_notes}"

    if context.recent_meetings:
        recent_objectives = "; ".join(m.objective[:100] for m in context.recent_meetings[:2])
        summary = f"{summary} Recent meetings: {recent_objectives}"

    if context.contact_memories:
        joined = "; ".join(mem.text for mem in context.contact_memories[:3])
        summary = f"{summary} Prior approved notes: {joined}"

    return summary[:2000]


class FakeBriefCoachAgent:
    """Async deterministic fake ``BriefCoachAgentPort`` consuming ``BriefPreparationContext``."""

    async def generate_brief(
        self,
        *,
        meeting: Meeting,
        context: BriefPreparationContext,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        del corrective_feedback
        with brew_span(
            "brew.agent.invoke",
            operation_name="agent.invoke",
            tracer_name=__name__,
            agent_name="conversation_coach",
            agent_version="1.0.0",
            model_name="fake-deterministic-coach",
        ):
            if attempt_metrics is not None:
                attempt_metrics.model_invocations += 1

        contact = context.contact
        user_preferences = context.user_preferences
        question_count = (
            user_preferences.preferred_question_count if user_preferences is not None else 6
        )
        question_count = max(1, min(question_count, 8))

        tone_label = meeting.tone.value.replace("_", " ")
        purpose_label = meeting.purpose.value.replace("_", " ")
        openers = [
            (
                f"Thanks for carving out {meeting.duration_minutes} minutes, {contact.name}. "
                f"Looking forward to our {purpose_label} conversation ({tone_label} style)."
            ),
            (
                f"Before we dive into {meeting.objective[:120]}, I'd love to hear what has been "
                f"top of mind for you recently."
            ),
        ]

        base_templates: list[tuple[str, str, str]] = [
            (
                (
                    f"Looking at {meeting.objective[:120]}, "
                    "what trade-offs have mattered most in practice?"
                ),
                (
                    f"Anchors the {purpose_label} objective in real-world decisions "
                    "rather than generic advice."
                ),
                "core_objective",
            ),
            (
                (
                    "What signal tells you an initiative in your domain is on the right track, "
                    f"{contact.name}?"
                ),
                "Surfaces concrete evaluation criteria aligned with the meeting goal.",
                "perspective",
            ),
            (
                "What common misconception do people bring when approaching this space?",
                "Invites candid nuance and memorable insights relevant to our discussion.",
                "nuance",
            ),
            (
                "Where do you see the biggest upcoming shift over the next two quarters?",
                "Opens forward-looking roadmap context for potential future conversations.",
                "outlook",
            ),
            (
                "Which habit or operating cadence helped your team navigate growing complexity?",
                "Connects practical execution lessons directly to our conversation objective.",
                "execution",
            ),
            (
                "Who or what resource shaped how you think about this problem?",
                "Creates natural follow-up threads and shared learning context.",
                "resources",
            ),
            (
                "When priorities collide, what framework helps you decide what to defer?",
                "Highlights concrete prioritization trade-offs tied to the meeting purpose.",
                "prioritization",
            ),
            (
                "Before we wrap, is there any context or connection that would be useful to you?",
                "Closes with reciprocity appropriate to relationship building.",
                "closing",
            ),
        ]

        questions = [
            ConversationQuestion(
                id=f"q_{idx + 1}",
                question=prompt[:400],
                rationale=rationale[:500],
                category=category,
            )
            for idx, (prompt, rationale, category) in enumerate(base_templates[:question_count])
        ]

        follow_ups = [
            f"Share a concise recap of key takeaways with {contact.name}.",
            (
                "Follow through on resources or next steps discussed around "
                f"{meeting.objective[:100]}."
            ),
        ]

        return GeneratedBriefContent(
            contact_context=_compose_contact_context(context),
            meeting_objective=meeting.objective,
            conversation_openers=openers,
            time_boxed_agenda=_build_time_boxed_agenda(
                duration_minutes=meeting.duration_minutes,
                purpose=meeting.purpose,
            ),
            suggested_questions=questions,
            suggested_follow_up_topics=follow_ups,
            referenced_memory_ids=context.referenced_memory_ids,
            revision_summary=None,
        )

    async def revise_brief(
        self,
        *,
        current_brief: PreparationBrief,
        meeting: Meeting,
        context: BriefPreparationContext,
        instructions: str,
        target_duration_minutes: MeetingDurationMinutes,
        target_tone: MeetingTone,
        corrective_feedback: Sequence[str] | None = None,
        attempt_metrics: BriefAttemptMetrics | None = None,
    ) -> GeneratedBriefContent:
        del corrective_feedback
        with brew_span(
            "brew.agent.invoke",
            operation_name="agent.invoke",
            tracer_name=__name__,
            agent_name="conversation_coach",
            agent_version="1.0.0",
            model_name="fake-deterministic-coach",
        ):
            if attempt_metrics is not None:
                attempt_metrics.model_invocations += 1

        contact = context.contact
        cleaned_instruction = scrub_basic_pii(instructions.strip())
        tone_label = target_tone.value.replace("_", " ")
        resolution = parse_refinement_overrides(
            cleaned_instruction,
            explicit_duration_minutes=target_duration_minutes,
            explicit_tone=target_tone,
            fallback_duration_minutes=current_brief.duration_minutes,
            fallback_tone=current_brief.tone,
        )

        updated_openers = [
            (
                f"Hi {contact.name}, glad we could catch up for {target_duration_minutes} "
                f"minutes ({tone_label}), excited to explore {cleaned_instruction[:140]}."
            ),
            (
                current_brief.conversation_openers[1]
                if len(current_brief.conversation_openers) > 1
                else (
                    f"Before jumping into {current_brief.meeting_objective[:110]}, how has "
                    "your week been unfolding?"
                )
            ),
        ]

        desired_count = len(current_brief.suggested_questions)
        rev_num = current_brief.version + 1

        if resolution.focus_customer_discovery:
            discovery_pool = [
                (
                    "Walk me through how your team currently handles this workflow end to end?",
                    "Grounds customer discovery in real current-state workflow behavior.",
                    "discovery_workflow",
                ),
                (
                    "Which step in that process creates the sharpest bottleneck or manual cost?",
                    "Identifies high-friction customer pain points worth solving.",
                    "discovery_pain",
                ),
                (
                    "What workarounds or tools have you already evaluated to solve this problem?",
                    "Surfaces existing alternatives and switching barriers for discovery.",
                    "discovery_alternatives",
                ),
                (
                    "How do you measure whether an onboarding or workflow improvement succeeded?",
                    "Links customer discovery findings to concrete evaluation metrics.",
                    "discovery_metrics",
                ),
                (
                    "Who else on the team feels this friction most acutely during adoption?",
                    "Maps stakeholder roles and adoption dynamics for the objective.",
                    "discovery_stakeholders",
                ),
                (
                    "What would need to be true for fixing this problem to become urgent now?",
                    "Tests priority and timing constraints against our discovery goal.",
                    "discovery_urgency",
                ),
            ]
            updated_questions = [
                ConversationQuestion(
                    id=f"q_disc_{rev_num}_{idx + 1}",
                    question=q_text,
                    rationale=r_text,
                    category=cat,
                )
                for idx, (q_text, r_text, cat) in enumerate(discovery_pool[: max(5, desired_count)])
            ]
        elif resolution.focus_engineering_career:
            eng_pool = [
                (
                    "Which technical project shifted your engineering career trajectory the most?",
                    "Connects concrete engineering career inflection points to our goal.",
                    "engineering_career",
                ),
                (
                    "How did your day-to-day system design scope change as you grew into senior "
                    "technical leadership?",
                    "Clarifies engineering role progression and technical scope trade-offs.",
                    "technical_scope",
                ),
                (
                    "What signal helped you decide between deepening IC architecture work versus "
                    "broader platform leadership?",
                    "Explores career ladder decisions aligned with the mentorship objective.",
                    "career_decisions",
                ),
                (
                    "Which production reliability or scaling failure taught you the most durable "
                    "engineering lesson?",
                    "Extracts grounded systems engineering wisdom without generic clichés.",
                    "systems_lessons",
                ),
                (
                    "How do you carve out time for hands-on technical context alongside org-wide "
                    "architecture reviews?",
                    "Addresses sustainable engineering operating habits for career growth.",
                    "operating_cadence",
                ),
                (
                    "What capability do engineers overlook when aiming for staff-plus impact?",
                    "Surfaces actionable coaching guidance linked to career advancement.",
                    "staff_growth",
                ),
            ]
            updated_questions = [
                ConversationQuestion(
                    id=f"q_eng_{rev_num}_{idx + 1}",
                    question=q_text,
                    rationale=r_text,
                    category=cat,
                )
                for idx, (q_text, r_text, cat) in enumerate(eng_pool[: max(5, desired_count)])
            ]
        elif resolution.avoid_prior_questions:
            fresh_pool = [
                (
                    f"In revision {rev_num}, what unexpected constraint reshaped how you view "
                    f"{current_brief.meeting_objective[:90]}?",
                    "Explores an unasked constraint angle tied to the meeting objective.",
                    "constraints",
                ),
                (
                    "Looking back at a recent launch, which early assumption turned out false?",
                    "Uncovers candid retrospective lessons not covered in earlier questions.",
                    "retrospective",
                ),
                (
                    "How do you align cross-functional partners when technical timelines tighten?",
                    "Examines stakeholder alignment mechanics relevant to our goal.",
                    "alignment",
                ),
                (
                    "What metric would make six months from now look like a clear success?",
                    "Anchors concrete outcome criteria for future follow-up sessions.",
                    "outcomes",
                ),
                (
                    "Which emerging tool or workflow change has genuinely saved your team time?",
                    "Surfaces practical operational leverage without repeating prior prompts.",
                    "leverage",
                ),
                (
                    "Who else in your ecosystem approaches this domain from a contrasting angle?",
                    "Opens fresh relationship threads and perspective diversity.",
                    "ecosystem",
                ),
            ]
            updated_questions = [
                ConversationQuestion(
                    id=f"q_fresh_{rev_num}_{idx + 1}",
                    question=q_text,
                    rationale=r_text,
                    category=cat,
                )
                for idx, (q_text, r_text, cat) in enumerate(fresh_pool[: max(5, desired_count)])
            ]
        else:
            updated_questions = list(current_brief.suggested_questions)
            updated_questions[0] = ConversationQuestion(
                id=updated_questions[0].id,
                question=(
                    f"With '{cleaned_instruction[:120]}' in mind, what practical decision stands "
                    f"out regarding {current_brief.meeting_objective[:110]}?"
                )[:400],
                rationale=(
                    f"Updated during revision v{rev_num} to advance the meeting objective "
                    "under caller guidance."
                ),
                category=updated_questions[0].category,
            )

        return GeneratedBriefContent(
            contact_context=_compose_contact_context(context),
            meeting_objective=current_brief.meeting_objective,
            conversation_openers=updated_openers,
            time_boxed_agenda=_build_time_boxed_agenda(
                duration_minutes=target_duration_minutes,
                purpose=meeting.purpose,
            ),
            suggested_questions=updated_questions,
            suggested_follow_up_topics=list(current_brief.suggested_follow_up_topics),
            referenced_memory_ids=context.referenced_memory_ids,
            revision_summary=f"Revised brief ({tone_label}): {cleaned_instruction}"[:1000],
        )
