"""Pydantic v2 HTTP request and response contracts for Brew API v1."""

from __future__ import annotations

from app.api.schemas.base import (
    ResponseModel,
    StrictRequestModel,
)
from app.api.schemas.briefs import (
    AgendaItemResponse,
    BriefRevisionListResponse,
    BriefWorkflowDiagnosticsResponse,
    ConversationQuestionResponse,
    GenerateBriefRequest,
    PreparationBriefResponse,
    ReviseBriefRequest,
    UserPreferencesInput,
)
from app.api.schemas.contacts import (
    ContactListResponse,
    ContactResponse,
    CreateContactRequest,
)
from app.api.schemas.errors import (
    ApiErrorResponse,
    ErrorDetailItem,
    ErrorObject,
)
from app.api.schemas.identity import (
    AuthenticatedPrincipalResponse,
)
from app.api.schemas.meetings import (
    MeetingListResponse,
    MeetingResponse,
)
from app.api.schemas.memories import (
    ApproveMemoryProposalRequest,
    MemoryListResponse,
    MemoryProposalBatchResponse,
    MemoryProposalResponse,
    MemoryResponse,
    MemorySourceResponse,
    ProposeMemoriesRequest,
    RejectMemoryProposalRequest,
    UpdateMemoryRequest,
)
from app.api.schemas.memory_jobs import (
    MemoryExtractionJobErrorResponse,
    MemoryExtractionJobResponse,
)

__all__ = [
    "AgendaItemResponse",
    "ApiErrorResponse",
    "ApproveMemoryProposalRequest",
    "AuthenticatedPrincipalResponse",
    "BriefRevisionListResponse",
    "BriefWorkflowDiagnosticsResponse",
    "ContactListResponse",
    "ContactResponse",
    "ConversationQuestionResponse",
    "CreateContactRequest",
    "ErrorDetailItem",
    "ErrorObject",
    "GenerateBriefRequest",
    "MeetingListResponse",
    "MeetingResponse",
    "MemoryExtractionJobErrorResponse",
    "MemoryExtractionJobResponse",
    "MemoryListResponse",
    "MemoryProposalBatchResponse",
    "MemoryProposalResponse",
    "MemoryResponse",
    "MemorySourceResponse",
    "PreparationBriefResponse",
    "ProposeMemoriesRequest",
    "RejectMemoryProposalRequest",
    "ResponseModel",
    "ReviseBriefRequest",
    "StrictRequestModel",
    "UpdateMemoryRequest",
    "UserPreferencesInput",
]
