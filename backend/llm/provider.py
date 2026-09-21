"""
vQA — LLM Provider Abstraction
=================================
Module: backend/llm/provider.py

Provider-agnostic factory for LLM clients with tiered model routing.

Currently supports:
  - **Bedrock** (default) — Claude Sonnet 4 (default + parser) / Sonnet 4 (heavy)
  - **OpenAI** — GPT-4o/4o-mini via OpenAI API (Phase 3)
  - **Anthropic** — Claude via direct Anthropic API (Phase 3)

Tiered Model Routing
--------------------
The factory supports three model tiers:

  - **Standard** (``settings.bedrock_model_id``) — Sonnet 4 (upgraded from Haiku 4.5 in FEAT-114).
    Used for most LLM calls (planner, verifier, evaluator, commander).
    $3.00/$15.00 per 1M in/out tokens.

  - **Heavy** (``settings.bedrock_model_id_heavy``) — Sonnet 4.
    Used on-demand when the planner auto-escalates after repeated
    self-heal failures. Same model as standard until bumped to Sonnet 5.

  - **Parser** (``settings.bedrock_model_id_parser``) — Sonnet 4 (FEAT-114).
    Used exclusively for the AC parser (Stage 1 BDD normalizer and Stage 2
    JSON compiler). Separated so parser quality is independently tunable.
    Callers request the parser model via ``get_llm("parser")``.

Callers request the heavy model via ``get_llm("planner", heavy=True)``.

Architecture Context
--------------------
Before Phase 1, ``ChatBedrockConverse`` was instantiated directly in
8 different modules.  Now ALL LLM instantiation goes through this
factory, enabling:
  - One-line provider swaps (bedrock → openai → anthropic)
  - Centralized token/temperature defaults per purpose
  - Tiered model routing without touching consumer code
  - Future: cost tracking, rate limiting, fallback chains

Usage
-----
    from backend.llm import get_llm

    # Standard planner (Haiku)
    llm = get_llm("planner")

    # Heavy planner (Sonnet — for complex self-heal retries)
    llm = get_llm("planner", heavy=True)

    # Fast verifier (100 tokens, Haiku)
    llm = get_llm("verifier_vision")

    # Override any parameter
    llm = get_llm("parser", max_tokens=4096, temperature=0.1)

See Also
--------
  - ``backend/config.py``  — bedrock_model_id, bedrock_model_id_heavy
"""

import logging
from typing import Any

from langchain_aws import ChatBedrockConverse

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Purpose-specific defaults
# ---------------------------------------------------------------------------

#: Default configuration per purpose.  Overridable via kwargs.
#: Each entry maps to a dict of ChatBedrockConverse parameters.
_PURPOSE_DEFAULTS: dict[str, dict[str, Any]] = {
    # ── Main pipeline (graph.py) ─────────────────────────────────────────
    "planner": {
        "temperature": 0.0,
        "max_tokens": 1024,
    },
    # FEAT-114: parser uses Sonnet (bedrock_model_id_parser) — larger output budget.
    # Stage 1 (BDD normalizer) produces up to 4096 tokens of BDD text.
    # Stage 2 (JSON compiler) overrides max_tokens=8192 at call site.
    "parser": {
        "temperature": 0.0,
        "max_tokens": 4096,
    },
    "evaluator": {
        "temperature": 0.0,
        "max_tokens": 512,
    },
    # ── Verifier (verifier.py — LLM-as-a-Judge fallback) ─────────────
    "verifier_vision": {
        "temperature": 0.0,
        "max_tokens": 100,  # Verdict is ~20 tokens; 100 is plenty
    },
    # ── Verifier node (verifier_node.py — orchestrator verifier) ──────
    "verifier_llm": {
        "temperature": 0.0,
        "max_tokens": 512,
    },
    # ── Failure analyzer (failure_analyzer.py) ────────────────────────
    "failure_analyzer": {
        "temperature": 0.0,
        "max_tokens": 1200,
    },
    # ── Graph orchestrator (graph_orchestrator.py) ────────────────────
    "commander": {
        "temperature": 0.0,
        "max_tokens": 4096,
    },
    "compiler": {
        "temperature": 0.0,
        "max_tokens": 512,  # Small JSON context spec
    },
    # ── Web surfer (web_surfer.py) ────────────────────────────────────
    "surfer": {
        "temperature": 0.0,
        "max_tokens": 4096,
    },
    # ── Supervisor (supervisor.py) ────────────────────────────────────
    "supervisor": {
        "temperature": 0.0,
        "max_tokens": 1024,
    },
    "vision_analyzer": {
        "temperature": 0.0,
        "max_tokens": 1024,
    },
    "review_rule_proposer": {
        "temperature": 0.0,
        "max_tokens": 800,
    },
}


# ---------------------------------------------------------------------------
# Bedrock provider
# ---------------------------------------------------------------------------


def _create_bedrock_llm(
    heavy: bool = False,
    parser_tier: bool = False,
    **kwargs: Any,
) -> ChatBedrockConverse:
    """
    Create a ChatBedrockConverse instance with settings from config.

    Parameters
    ----------
    heavy : bool
        When True, uses ``settings.bedrock_model_id_heavy`` (Sonnet)
        instead of the default ``settings.bedrock_model_id`` (Haiku).
    parser_tier : bool
        When True, uses ``settings.bedrock_model_id_parser`` (Sonnet).
        Takes precedence over ``heavy``. Used exclusively for the AC
        parser (Stage 1 + Stage 2) per FEAT-114.

    **kwargs
        Override any ChatBedrockConverse parameter.
        Common overrides: ``temperature``, ``max_tokens``, ``model``.

    Returns
    -------
    ChatBedrockConverse
        A LangChain chat model configured for AWS Bedrock.
    """
    if parser_tier:
        model = settings.bedrock_model_id_parser
    elif heavy:
        model = settings.bedrock_model_id_heavy
    else:
        model = settings.bedrock_model_id
    params: dict[str, Any] = {
        "model": model,
        "region_name": settings.aws_bedrock_region,
    }
    params.update(kwargs)
    return ChatBedrockConverse(**params)


# ---------------------------------------------------------------------------
# Public factory function
# ---------------------------------------------------------------------------


def get_llm(
    purpose: str = "planner",
    heavy: bool = False,
    **overrides: Any,
) -> ChatBedrockConverse:
    """
    Create an LLM client for the given purpose.

    Reads ``settings.llm_provider`` to select the backend.
    Purpose-specific defaults (temperature, max_tokens) are applied
    first, then any explicit ``**overrides`` take precedence.

    Parameters
    ----------
    purpose : str
        What the LLM is being used for.  Determines default config.
        One of: ``"planner"``, ``"parser"``, ``"evaluator"``,
        ``"verifier_vision"``, ``"verifier_llm"``, ``"failure_analyzer"``,
        ``"commander"``, ``"compiler"``, ``"surfer"``, ``"supervisor"``.

        **FEAT-114**: ``"parser"`` automatically uses
        ``settings.bedrock_model_id_parser`` (Sonnet 4) — no need to pass
        ``heavy=True``. All other purposes use the standard Haiku tier.

    heavy : bool
        When True, uses the heavy model tier (Sonnet) instead of the
        default (Haiku).  Typically used for planner auto-escalation
        after repeated self-heal failures.

    **overrides
        Override any provider-specific parameter.
        Example: ``get_llm("planner", temperature=0.2)``

    Returns
    -------
    ChatBedrockConverse
        A configured LLM client.  Return type will become a Union
        when OpenAI/Anthropic providers are added in Phase 3.

    Example
    -------
    >>> llm = get_llm("planner")
    >>> type(llm).__name__
    'ChatBedrockConverse'

    >>> llm = get_llm("planner", heavy=True)
    >>> # Uses Sonnet for complex reasoning

    >>> llm = get_llm("parser")
    >>> # FEAT-114: Uses Sonnet (bedrock_model_id_parser) for AC parsing
    """
    # Resolve purpose-specific defaults
    defaults = dict(_PURPOSE_DEFAULTS.get(purpose, _PURPOSE_DEFAULTS["planner"]))
    defaults.update(overrides)

    provider = settings.llm_provider.lower()

    # FEAT-114: parser purpose always uses the dedicated parser model tier (Sonnet).
    # This check must come before the provider dispatch so it applies to all providers.
    is_parser_tier = purpose == "parser"

    if provider == "bedrock":
        return _create_bedrock_llm(heavy=heavy, parser_tier=is_parser_tier, **defaults)

    # Phase 3: OpenAI and Anthropic providers
    # elif provider == "openai":
    #     return _create_openai_llm(heavy=heavy, **defaults)
    # elif provider == "anthropic":
    #     return _create_anthropic_llm(heavy=heavy, **defaults)

    logger.warning(
        "Unknown LLM provider '%s' — falling back to Bedrock",
        provider,
    )
    return _create_bedrock_llm(heavy=heavy, parser_tier=is_parser_tier, **defaults)
