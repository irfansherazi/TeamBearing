"""
TASK-069: AC Step Caching Tests
================================

Tests for backend/jira/cache.py::ACStepCache.
Verifies that parsed AC steps are cached and isolated by domain, ticket ID, and guidance.
"""

import asyncio

import pytest

from backend.jira.cache import ACStepCache


@pytest.fixture
def cache():
    return ACStepCache(ttl_seconds=60.0)

_SAMPLE_TICKET = {
    "ticket_id": "QA-123",
    "summary": "Sample Ticket",
    "description": "Original description",
    "acceptance_criteria": "Original AC",
    "attachments": []
}

_SAMPLE_RESULT = {
    "acceptance_criteria_steps": ["Step 1", "Step 2"],
    "test_plan": {"steps": []}
}

@pytest.mark.asyncio
async def test_ac_cache_hit(cache):
    # Set entry
    await cache.set("prod", "QA-123", "No guidance", _SAMPLE_TICKET, _SAMPLE_RESULT)

    # Get entry
    hit = await cache.get("prod", "QA-123", "No guidance", _SAMPLE_TICKET)
    assert hit == _SAMPLE_RESULT

@pytest.mark.asyncio
async def test_ac_cache_miss_different_guidance(cache):
    # Set entry
    await cache.set("prod", "QA-123", "Old guidance", _SAMPLE_TICKET, _SAMPLE_RESULT)

    # Get with different guidance -> MISS
    miss = await cache.get("prod", "QA-123", "New guidance", _SAMPLE_TICKET)
    assert miss is None

@pytest.mark.asyncio
async def test_ac_cache_miss_different_ticket_data(cache):
    # Set entry
    await cache.set("prod", "QA-123", "", _SAMPLE_TICKET, _SAMPLE_RESULT)

    # Modify ticket AC
    new_ticket = _SAMPLE_TICKET.copy()
    new_ticket["acceptance_criteria"] = "Changed AC"

    # Get with modified ticket -> MISS
    miss = await cache.get("prod", "QA-123", "", new_ticket)
    assert miss is None

@pytest.mark.asyncio
async def test_ac_cache_evict(cache):
    cache._ttl = 0.01 # 10ms TTL
    await cache.set("prod", "QA-123", "", _SAMPLE_TICKET, _SAMPLE_RESULT)

    await asyncio.sleep(0.05)
    miss = await cache.get("prod", "QA-123", "", _SAMPLE_TICKET)
    assert miss is None

@pytest.mark.asyncio
async def test_ac_cache_attachment_dependency(cache):
    t1 = _SAMPLE_TICKET.copy()
    t1["attachments"] = [{"id": "att-1"}]

    t2 = _SAMPLE_TICKET.copy()
    t2["attachments"] = [{"id": "att-2"}]

    await cache.set("prod", "QA-123", "", t1, _SAMPLE_RESULT)

    # Different attachment -> MISS
    miss = await cache.get("prod", "QA-123", "", t2)
    assert miss is None

    # Same attachment -> HIT
    hit = await cache.get("prod", "QA-123", "", t1)
    assert hit == _SAMPLE_RESULT
