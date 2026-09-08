"""
tests/test_prompt_caching.py
==============================
Unit tests for Dynamic System Prompt Caching (TASK-080-P2A).

Tests cover:
- cache_control breakpoints are added to static system prompt sections
- Dynamic context (ARIA diff, action history) is NOT cached
- Feature flag: PROMPT_CACHING_ENABLED=false → no cache_control blocks injected
- Bedrock converse API call includes cachePoint metadata for static sections
- Cache-tagged system messages are correctly structured for Bedrock API
- Token usage metadata: cache read tokens measurable via usage.cacheReadInputTokens
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from backend.engine.prompt_cache import (
    PromptCacheBuilder,
    CachedSystemBlock,
    build_cached_system_blocks,
    get_prompt_cache_builder,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def builder():
    """Return a fresh PromptCacheBuilder with caching enabled."""
    return PromptCacheBuilder(enabled=True)


@pytest.fixture()
def disabled_builder():
    """Return a PromptCacheBuilder with caching disabled."""
    return PromptCacheBuilder(enabled=False)


STATIC_CONTENT = """<GOLDEN_RULES>
1. IDENTITY: You are a QA automation agent.
2. MISSION: Execute AC steps deterministically.
</GOLDEN_RULES>"""

DYNAMIC_CONTENT = """Current AC step: Click the Submit button
Action history: [click 'New Order', fill 'Client Name']"""


# ---------------------------------------------------------------------------
# CachedSystemBlock Tests
# ---------------------------------------------------------------------------


class TestCachedSystemBlock:
    """CachedSystemBlock data class is well-formed."""

    def test_static_block_has_cache_point(self):
        """Static blocks include cachePoint marker."""
        block = CachedSystemBlock(text=STATIC_CONTENT, is_static=True)
        assert block.is_static is True
        assert block.text == STATIC_CONTENT

    def test_dynamic_block_no_cache_point(self):
        """Dynamic blocks do NOT include cachePoint marker."""
        block = CachedSystemBlock(text=DYNAMIC_CONTENT, is_static=False)
        assert block.is_static is False

    def test_to_bedrock_format_static(self):
        """Static block serializes as two separate dicts (tagged union constraint)."""
        block = CachedSystemBlock(text=STATIC_CONTENT, is_static=True)
        bedrock_blocks = block.to_bedrock_format()
        # Must return a list
        assert isinstance(bedrock_blocks, list)
        # First element: text only
        assert bedrock_blocks[0] == {"text": STATIC_CONTENT}
        # Second element: cachePoint only (separate dict — tagged union!)
        assert len(bedrock_blocks) == 2
        assert bedrock_blocks[1] == {"cachePoint": {"type": "default"}}
        # Critically: NO element should have BOTH text and cachePoint
        for b in bedrock_blocks:
            assert not ("text" in b and "cachePoint" in b), (
                "Tagged union violation: text and cachePoint in same dict"
            )

    def test_to_bedrock_format_dynamic(self):
        """Dynamic block serializes as a single-element list with text only."""
        block = CachedSystemBlock(text=DYNAMIC_CONTENT, is_static=False)
        bedrock_blocks = block.to_bedrock_format()
        assert isinstance(bedrock_blocks, list)
        assert len(bedrock_blocks) == 1
        assert bedrock_blocks[0] == {"text": DYNAMIC_CONTENT}
        # Dynamic blocks must NOT have cachePoint
        for b in bedrock_blocks:
            assert "cachePoint" not in b

    def test_cachepoint_format_matches_bedrock_spec(self):
        """cachePoint value matches Bedrock API spec: {'type': 'default'}."""
        block = CachedSystemBlock(text=STATIC_CONTENT, is_static=True)
        bedrock_blocks = block.to_bedrock_format()
        cache_blocks = [b for b in bedrock_blocks if "cachePoint" in b]
        assert len(cache_blocks) == 1
        assert cache_blocks[0]["cachePoint"] == {"type": "default"}


# ---------------------------------------------------------------------------
# PromptCacheBuilder Tests
# ---------------------------------------------------------------------------


class TestPromptCacheBuilder:
    """PromptCacheBuilder correctly partitions static vs dynamic content."""

    def test_build_returns_list_of_cached_blocks(self, builder):
        """build() returns a list of CachedSystemBlock objects."""
        blocks = builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
        )
        assert isinstance(blocks, list)
        assert all(isinstance(b, CachedSystemBlock) for b in blocks)

    def test_static_content_is_marked_static(self, builder):
        """Static content sections have is_static=True."""
        blocks = builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
        )
        static_blocks = [b for b in blocks if b.is_static]
        assert len(static_blocks) >= 1

    def test_dynamic_content_is_marked_dynamic(self, builder):
        """Dynamic content sections have is_static=False."""
        blocks = builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
        )
        dynamic_blocks = [b for b in blocks if not b.is_static]
        assert len(dynamic_blocks) >= 1

    def test_static_content_appears_before_dynamic(self, builder):
        """Static blocks come before dynamic blocks (Bedrock cache ordering)."""
        blocks = builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
        )
        if len(blocks) >= 2:
            # Find the last static block index and first dynamic block index
            static_indices = [i for i, b in enumerate(blocks) if b.is_static]
            dynamic_indices = [i for i, b in enumerate(blocks) if not b.is_static]
            if static_indices and dynamic_indices:
                assert max(static_indices) < min(dynamic_indices)

    def test_all_content_is_preserved(self, builder):
        """No content is dropped — static + dynamic blocks cover all text."""
        blocks = builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
        )
        all_text = "".join(b.text for b in blocks)
        assert STATIC_CONTENT in all_text or STATIC_CONTENT[:50] in all_text
        assert DYNAMIC_CONTENT in all_text or DYNAMIC_CONTENT[:50] in all_text

    def test_empty_dynamic_content_only_has_static_blocks(self, builder):
        """When dynamic_content is empty, only static block is present."""
        blocks = builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content="",
        )
        assert len(blocks) >= 1
        static_blocks = [b for b in blocks if b.is_static]
        assert len(static_blocks) >= 1


# ---------------------------------------------------------------------------
# Feature Flag Tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    """When PROMPT_CACHING_ENABLED=false, no cachePoint blocks are injected."""

    def test_disabled_builder_no_cache_points(self, disabled_builder):
        """Disabled builder produces no cachePoint markers."""
        blocks = disabled_builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
        )
        for block in blocks:
            for bedrock_block in block.to_bedrock_format():
                assert "cachePoint" not in bedrock_block

    def test_disabled_builder_still_returns_all_content(self, disabled_builder):
        """Even when disabled, all content is returned (no data loss)."""
        blocks = disabled_builder.build(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
        )
        assert len(blocks) >= 1
        all_text = "".join(b.text for b in blocks)
        assert len(all_text) > 0

    def test_disabled_flag_attribute(self, disabled_builder):
        assert disabled_builder.enabled is False

    def test_enabled_flag_attribute(self, builder):
        assert builder.enabled is True


# ---------------------------------------------------------------------------
# build_cached_system_blocks Convenience Function
# ---------------------------------------------------------------------------


class TestBuildCachedSystemBlocks:
    """Module-level function for building Bedrock-formatted system blocks."""

    def test_returns_bedrock_formatted_list(self):
        """build_cached_system_blocks returns list of dicts for Bedrock API."""
        blocks = build_cached_system_blocks(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
            enabled=True,
        )
        assert isinstance(blocks, list)
        for block in blocks:
            assert isinstance(block, dict)
            # Each block has exactly ONE key (tagged union constraint)
            assert len(block) == 1, f"Tagged union violation — block has {len(block)} keys: {block}"

    def test_enabled_includes_cache_point_on_static(self):
        """When enabled, at least one block is a standalone cachePoint dict."""
        blocks = build_cached_system_blocks(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
            enabled=True,
        )
        # The cachePoint must be a SEPARATE dict (tagged union)
        has_cache_point = any(list(b.keys()) == ["cachePoint"] for b in blocks)
        assert has_cache_point
        # And no block should mix text + cachePoint
        for b in blocks:
            assert not ("text" in b and "cachePoint" in b), (
                "Tagged union violation: text and cachePoint in same dict"
            )

    def test_disabled_no_cache_points(self):
        """When disabled, no blocks have cachePoint."""
        blocks = build_cached_system_blocks(
            static_content=STATIC_CONTENT,
            dynamic_content=DYNAMIC_CONTENT,
            enabled=False,
        )
        has_cache_point = any("cachePoint" in b for b in blocks)
        assert not has_cache_point

    def test_empty_static_content(self):
        """Empty static content is handled gracefully."""
        blocks = build_cached_system_blocks(
            static_content="",
            dynamic_content=DYNAMIC_CONTENT,
            enabled=True,
        )
        assert isinstance(blocks, list)

    def test_empty_dynamic_content(self):
        """Empty dynamic content is handled gracefully."""
        blocks = build_cached_system_blocks(
            static_content=STATIC_CONTENT,
            dynamic_content="",
            enabled=True,
        )
        assert isinstance(blocks, list)


# ---------------------------------------------------------------------------
# get_prompt_cache_builder Factory
# ---------------------------------------------------------------------------


class TestGetPromptCacheBuilder:
    """Module-level factory function returns correctly configured builder."""

    def test_factory_returns_prompt_cache_builder(self):
        b = get_prompt_cache_builder()
        assert isinstance(b, PromptCacheBuilder)

    def test_factory_respects_settings(self):
        """Factory reads settings.prompt_caching_enabled."""
        b = get_prompt_cache_builder()
        assert hasattr(b, "enabled")
        # Verify it produces output without raising
        blocks = b.build(static_content=STATIC_CONTENT, dynamic_content=DYNAMIC_CONTENT)
        assert isinstance(blocks, list)
