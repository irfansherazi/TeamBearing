"""
vQA — Run Metrics
===================
Module: backend/engine/metrics.py

Per-run observability dataclass tracking LLM usage, cost estimates,
model tier usage, and timing.

Usage
-----
    from backend.engine.metrics import RunMetrics

    metrics = RunMetrics()
    metrics.record_llm_call(
        purpose="planner",
        model_id="us.anthropic.claude-3-5-haiku-20241022-v1:0",
        input_tokens=1200,
        output_tokens=350,
        latency_ms=680,
    )
    print(metrics.to_dict())

Pricing
-------
    Haiku 4.5:  $1.00 / 1M input,  $5.00 / 1M output
    Sonnet 4:   $3.00 / 1M input, $15.00 / 1M output
    Sonnet 5:   $2.00 / 1M input, $10.00 / 1M output  (promo through Aug 31 2026)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (USD) — updated July 2026
_PRICING: dict[str, dict[str, float]] = {
    "haiku": {"input": 1.00, "output": 5.00},    # Haiku 4.5
    "sonnet": {"input": 3.00, "output": 15.00},  # Sonnet 4 / Sonnet 4.6
    "sonnet5": {"input": 2.00, "output": 10.00}, # Sonnet 5 (promo through Aug 31 2026)
}


def _classify_model_tier(model_id: str) -> str:
    """Classify a Bedrock model ID as 'haiku' or 'sonnet'."""
    model_lower = model_id.lower()
    if "sonnet" in model_lower:
        return "sonnet"
    return "haiku"


@dataclass
class RunMetrics:
    """
    Per-run metrics for LLM usage, cost, and performance.

    Thread-safe — all mutations are protected by a lock.

    Attributes
    ----------
    llm_calls : int
        Total LLM invocations across all purposes.
    llm_calls_heavy : int
        Calls that used the heavy (Sonnet) model.
    total_input_tokens : int
        Cumulative input tokens across all calls.
    total_output_tokens : int
        Cumulative output tokens across all calls.
    estimated_cost_usd : float
        Running cost estimate based on Haiku/Sonnet pricing.
    total_llm_time_ms : int
        Cumulative LLM response latency in milliseconds.
    escalations : int
        Number of Haiku→Sonnet auto-escalations.
    calls_by_purpose : dict[str, int]
        Breakdown of call counts by purpose (planner, verifier, etc.).
    """

    llm_calls: int = 0
    llm_calls_heavy: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    vision_input_tokens: int = 0  # FEAT-049 / TASK-047
    vision_output_tokens: int = 0  # FEAT-049 / TASK-047
    estimated_cost_usd: float = 0.0
    vision_cost_usd: float = 0.0  # FEAT-049 / TASK-047
    total_llm_time_ms: int = 0
    escalations: int = 0
    calls_by_purpose: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_llm_call(
        self,
        purpose: str,
        model_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        was_escalation: bool = False,
    ) -> None:
        """
        Record a single LLM invocation.

        Parameters
        ----------
        purpose : str
            LLM purpose (e.g., "planner", "verifier_vision", "vision_analyzer").
        model_id : str
            Bedrock model ID used.
        input_tokens : int
            Number of input tokens consumed.
        output_tokens : int
            Number of output tokens generated.
        latency_ms : int
            Response latency in milliseconds.
        was_escalation : bool
            True if this call was triggered by auto-escalation.
        """
        tier = _classify_model_tier(model_id)
        pricing = _PRICING.get(tier, _PRICING["haiku"])

        cost = (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing["output"]

        with self._lock:
            self.llm_calls += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.estimated_cost_usd += cost
            self.total_llm_time_ms += latency_ms

            if purpose in ("vision_analyzer", "verifier_vision"):
                self.vision_input_tokens += input_tokens
                self.vision_output_tokens += output_tokens
                self.vision_cost_usd += cost

            if tier == "sonnet":
                self.llm_calls_heavy += 1

            if was_escalation:
                self.escalations += 1

            self.calls_by_purpose[purpose] = self.calls_by_purpose.get(purpose, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        """
        Export metrics as a JSON-serializable dict.

        Returns
        -------
        dict
            All metrics fields as a plain dict.
        """
        with self._lock:
            return {
                "llm_calls": self.llm_calls,
                "llm_calls_heavy": self.llm_calls_heavy,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "vision_token_usage": {
                    "input": self.vision_input_tokens,
                    "output": self.vision_output_tokens,
                    "cost_usd": round(self.vision_cost_usd, 6),
                },
                "estimated_cost_usd": round(self.estimated_cost_usd, 6),
                "total_llm_time_ms": self.total_llm_time_ms,
                "escalations": self.escalations,
                "calls_by_purpose": dict(self.calls_by_purpose),
                "avg_latency_ms": (round(self.total_llm_time_ms / self.llm_calls) if self.llm_calls > 0 else 0),
            }

    def __str__(self) -> str:
        d = self.to_dict()
        return (
            f"RunMetrics: {d['llm_calls']} calls "
            f"({d['llm_calls_heavy']} heavy), "
            f"${d['estimated_cost_usd']:.4f}, "
            f"{d['total_input_tokens']}+{d['total_output_tokens']} tokens, "
            f"avg {d['avg_latency_ms']}ms"
        )


# ---------------------------------------------------------------------------
# Module-level per-run metrics registry
# ---------------------------------------------------------------------------
# Since VQAState is a TypedDict (can't hold non-serializable objects),
# we use a module-level dict keyed by run_id to hold live RunMetrics.

_run_metrics_registry: dict[str, RunMetrics] = {}
_registry_lock = threading.Lock()


def get_run_metrics(run_id: str) -> RunMetrics:
    """
    Get or create a RunMetrics instance for a run.

    Thread-safe. Creates a new instance on first access.

    Parameters
    ----------
    run_id : str
        The unique run identifier.

    Returns
    -------
    RunMetrics
        The per-run metrics collector.
    """
    with _registry_lock:
        if run_id not in _run_metrics_registry:
            _run_metrics_registry[run_id] = RunMetrics()
            logger.debug("Created RunMetrics for run '%s'", run_id)
        return _run_metrics_registry[run_id]


def remove_run_metrics(run_id: str) -> dict:
    """
    Remove and return the final metrics dict for a completed run.

    Parameters
    ----------
    run_id : str
        The unique run identifier.

    Returns
    -------
    dict
        The final metrics as a JSON-serializable dict.
        Empty dict if no metrics were recorded.
    """
    with _registry_lock:
        metrics = _run_metrics_registry.pop(run_id, None)
    if metrics is not None:
        result = metrics.to_dict()
        logger.info("[%s] Final run metrics: %s", run_id, metrics)
        return result
    return {}
