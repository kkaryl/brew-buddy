"""Firestore collection and subcollection names for Brew's per-user document tree."""

from __future__ import annotations

USERS_COLLECTION = "users"


PREFERENCES_SUBCOLLECTION = "preferences"


DEFAULT_PREFERENCES_DOC_ID = "default"


CONTACTS_SUBCOLLECTION = "contacts"


MEETINGS_SUBCOLLECTION = "meetings"


BRIEFS_SUBCOLLECTION = "briefs"


BRIEF_REVISIONS_SUBCOLLECTION = "revisions"


MEMORIES_SUBCOLLECTION = "memories"


DELETED_MEMORIES_SUBCOLLECTION = "deletedMemories"


MEMORY_PROPOSALS_SUBCOLLECTION = "memoryProposals"


WORKFLOW_IDEMPOTENCY_SUBCOLLECTION = "workflowIdempotency"


MEMORY_JOBS_SUBCOLLECTION = "memoryJobs"
