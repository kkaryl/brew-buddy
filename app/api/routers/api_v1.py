"""Assembles the per-context routers into the single /api/v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import briefs, contacts, identity, meetings, memories, memory_jobs

# Each context router declares the /api/v1 prefix and the shared error responses itself, so
# the route object FastAPI exposes as scope["route"] keeps its full path. This router adds
# nothing to them. Inclusion order is route registration order and must stay as it is.
router = APIRouter()
router.include_router(identity.router)
router.include_router(briefs.router)
router.include_router(contacts.router)
router.include_router(meetings.router)
router.include_router(memories.proposal_intake_router)
router.include_router(memory_jobs.router)
router.include_router(memories.router)
