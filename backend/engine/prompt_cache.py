"""
backend/engine/prompt_cache.py
================================
TASK-080-P2A: Dynamic System Prompt Caching for FEAT-060.

Leverages Anthropic's `cache_control` breakpoints in the Bedrock converse
API to cache static system prompt sections (tool schemas, global rules,
recipe library), reducing input token cost by 60-80% on turns 2+ of a run.

Only dynamic context (current AC step, ARIA diff, action history) is
re-sent each turn. Static content is cached at the Bedrock layer and
returned as cache read tokens (much cheaper than standard input tokens).

Bedrock converse format for cached system blocks:
    [
        {"text": "<GOLDEN_RULES>...</GOLDEN_RULES>"},
        {"cachePoint": {"type": "default"}},
        {"text": "<current_ac_step>...</current_ac_step>"}   # no cachePoint
    ]

CRITICAL: The Bedrock converse ``system`` parameter is a tagged union — each
array element may contain ONLY ONE of: text, cachePoint, guardContent.
Do NOT combine text and cachePoint into a single dict — this causes:
    "Parameter validation failed: Invalid number of parameters set for
     tagged union structure system[0]. Can only set one of the following
     keys: text, guardContent, cachePoint."
The cachePoint block must be a SEPARATE dict element immediately after
the text block it annotates.

Feature flag: PROMPT_CACHING_ENABLED (default true)
  When false: no cachePoint markers are added — standard input tokens charged.

Design: See TASK-080 Specification Item 4.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)

# The Bedrock cache point specification per API contract
_CACHE_POINT = {"type": "default"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CachedSystemBlock:
    """
    A system prompt block with optional Bedrock cachePoint annotation.

    Attributes:
        text:      The raw text content of this block.
        is_static: When True and caching is enabled, adds a cachePoint
                   marker when serialized to Bedrock API format. Static
                   content (tool schemas, global rules) changes rarely and
                   is safe to cache across turns.
    """

    text: str
    is_static: bool = False

    def to_bedrock_format(self) -> list[dict]:
        """
        Serialize to Bedrock converse API system block format.

        IMPORTANT: The Bedrock converse ``system`` parameter is a **tagged
        union** — each array element may contain ONLY ONE key (text,
        cachePoint, or guardContent).  Combining text + cachePoint into a
        single dict causes a parameter validation error:
            "Can only set one of the following keys: text, guardContent, cachePoint"

        For a static (cacheable) block this method therefore returns TWO
        separate dicts:
            [{"text": "..."}, {"cachePoint": {"type": "default"}}]

        For a dynamic (non-cached) block it returns ONE dict:
            [{"text": "..."}]

        The caller (``to_bedrock_system``) is responsible for flattening
        these lists into the final ``system`` array.

        Returns:
            list[dict] — one or two Bedrock system block dicts.
        """
        blocks: list[dict] = [{"text": self.text}]
        if self.is_static:
            blocks.append({"cachePoint": _CACHE_POINT})
        return blocks


# ---------------------------------------------------------------------------
# PromptCacheBuilder
# ---------------------------------------------------------------------------


class PromptCacheBuilder:
    """
    Build Bedrock-formatted system prompt blocks with cache_control markers.

    Partitions the system prompt into:
      - Static content (tool schemas, global rules, recipe library):
        Annotated with cachePoint for Bedrock prompt caching.
      - Dynamic content (current AC step, ARIA diff, action history):
        NOT annotated — re-sent each turn (changes every iteration).

    Static blocks are ordered BEFORE dynamic blocks per Bedrock's caching
    semantics: the cache boundary applies at the position of the cachePoint,
    so static content must come first in the system array.

    Args:
        enabled: When False, no cachePoint markers are added — standard
                 input tokens are charged (pre-FEAT-060 behavior).
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        static_content: str,
        dynamic_content: str,
    ) -> list[CachedSystemBlock]:
        """
        Partition system prompt content into cached static + dynamic blocks.

        Args:
            static_content: Content that changes rarely (tool schemas, global
                            rules, recipe library, RBAC constraints).
                            Will be marked with cachePoint when enabled.
            dynamic_content: Content that changes every turn (current AC step,
                             ARIA diff, action history, failure diary).
                             Never marked with cachePoint.

        Returns:
            List of CachedSystemBlock objects in cache-optimal order
            (static blocks first, dynamic blocks last).
        """
        blocks: list[CachedSystemBlock] = []

        # ── Static block: cacheable content ───────────────────────
        if static_content:
            static_block = CachedSystemBlock(
                text=static_content,
                # Only mark as static (cacheable) when feature flag is on
                is_static=self.enabled,
            )
            blocks.append(static_block)
            if self.enabled:
                logger.debug(
                    "prompt_cache: static block added (%d chars, cachePoint=true)",
                    len(static_content),
                )

        # ── Dynamic block: per-turn content, never cached ──────────
        if dynamic_content:
            dynamic_block = CachedSystemBlock(
                text=dynamic_content,
                is_static=False,  # Never cached — always re-sent
            )
            blocks.append(dynamic_block)
            logger.debug(
                "prompt_cache: dynamic block added (%d chars, cachePoint=false)",
                len(dynamic_content),
            )

        return blocks

    def to_bedrock_system(
        self,
        static_content: str,
        dynamic_content: str,
    ) -> list[dict]:
        """
        Build and serialize to Bedrock converse API ``system`` parameter format.

        Convenience method combining build() and serialization.

        Args:
            static_content: Cacheable static content.
            dynamic_content: Per-turn dynamic content.

        Returns:
            List of dicts formatted for the Bedrock converse API ``system``
            parameter.  Each element contains exactly ONE key (tagged union
            constraint).  Example::

                [
                    {"text": "..."},
                    {"cachePoint": {"type": "default"}},
                    {"text": "..."}
                ]
        """
        blocks = self.build(static_content=static_content, dynamic_content=dynamic_content)
        # Each block.to_bedrock_format() returns a list[dict]; flatten into
        # a single list so the system array satisfies the tagged union constraint.
        result: list[dict] = []
        for block in blocks:
            result.extend(block.to_bedrock_format())
        return result


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def build_cached_system_blocks(
    static_content: str,
    dynamic_content: str,
    enabled: bool = True,
) -> list[dict]:
    """
    Build Bedrock-formatted system blocks with optional cachePoint markers.

    This is a stateless convenience function for use in call sites that
    don't need the full PromptCacheBuilder API.

    Args:
        static_content:  Cacheable static system prompt sections.
        dynamic_content: Per-turn dynamic content.
        enabled:         When True, adds cachePoint to static blocks.

    Returns:
        List of dicts formatted for the Bedrock ``system`` parameter.
    """
    builder = PromptCacheBuilder(enabled=enabled)
    return builder.to_bedrock_system(static_content=static_content, dynamic_content=dynamic_content)


# ---------------------------------------------------------------------------
# Module-level singleton factory
# ---------------------------------------------------------------------------


def get_prompt_cache_builder() -> PromptCacheBuilder:
    """
    Return the singleton PromptCacheBuilder, respecting the feature flag.

    Import pattern::

        from backend.engine.prompt_cache import get_prompt_cache_builder
        builder = get_prompt_cache_builder()

    This is intentionally NOT a module-level singleton to keep tests simple.
    """
    return PromptCacheBuilder(
        enabled=getattr(settings, "prompt_caching_enabled", True),
    )
