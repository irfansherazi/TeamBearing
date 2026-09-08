"""
vQA Engine — LangGraph State Machine Package
=============================================

This package contains the core autonomous testing engine built on
LangGraph.  It defines the state schema, graph topology, and all
node implementations for the see-think-act loop.

Modules
-------
state.py
    ``VQAState`` TypedDict and sub-types (``ExecutionStep``,
    ``RoleContext``, ``JiraTicketContext``).  The shared data contract
    flowing through every graph node.

graph.py
    ``StateGraph`` wiring — declares nodes, edges, and conditional
    routing (planner → executor → evaluator → reporter).

planner.py
    Multimodal planning node.  Takes a screenshot + accessibility tree,
    sends them to Claude 3.5 Sonnet, and receives a structured JSON
    action describing the next browser interaction.

executor.py
    Action dispatcher.  Reads ``planned_action`` from state and
    translates it into a Playwright locator call (``get_by_role``,
    ``get_by_text``, etc.).

evaluator.py
    Step validator.  Determines whether the action succeeded, whether
    the current AC step is satisfied, and whether to retry, advance,
    or finish the run.

reporter.py
    HTML audit report generator.  Synthesises the ``detailed_execution_log``
    into a self-contained HTML file with embedded ``.webm`` video player,
    step-by-step screenshot gallery, and LLM reasoning trace.

roles.py
    Role registry mapping role keys to credentials, permissions,
    and LLM planning constraints.  Credentials are loaded from ``.env``.
"""
