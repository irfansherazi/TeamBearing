"""
Computer-Use loop: a minimal Maestro/Claude-Computer-Use-style entrypoint.

New in feature/computer-use-loop. Additive to the existing LangGraph pipeline —
does not import or modify planner.py, executor.py, evaluator.py, verifier.py,
critic_node.py, reflex/, recovery_router.py, ac_parser.py, ac_enricher.py, or
any of backend/kb/. Existing /execute path is untouched.

Reuses (import-only, no modification):
    - backend/browser/context.py       (browser + video recording)
    - backend/jira/client.py           (ticket fetch)
    - backend/engine/ghost_login_node  (admin auth primitives)
    - backend/engine/persona_switch_node (credential + SPA-render helpers)
    - backend/engine/human_takeover    (HITL fallback event API)
"""

from backend.engine.computer_use.runner import run_computer_use

__all__ = ["run_computer_use"]
