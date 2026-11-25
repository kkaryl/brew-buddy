"""Meeting purpose, tone and status enumerations."""

from __future__ import annotations

from enum import StrEnum


class MeetingPurpose(StrEnum):
    """Supported meeting archetypes in Brew."""

    COFFEE_CHAT = "coffee_chat"
    NETWORKING = "networking"
    MENTORSHIP = "mentorship"
    CUSTOMER_DISCOVERY = "customer_discovery"


class MeetingTone(StrEnum):
    """Supported coaching and conversation tones."""

    WARM_CASUAL = "warm_casual"
    CURIOUS_EXPLORATORY = "curious_exploratory"
    STRUCTURED_EXECUTIVE = "structured_executive"
    CANDID_COACHING = "candid_coaching"


class MeetingStatus(StrEnum):
    """Lifecycle states of a meeting session."""

    PREPARING = "preparing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
