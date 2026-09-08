"""
vQA Backend — Top-Level Package
================================

The ``backend`` package contains the entire vQA server-side application:

Subpackages
-----------
api/
    FastAPI route handlers, Pydantic request/response schemas,
    and WebSocket endpoints for real-time log streaming.

browser/
    Playwright infrastructure — browser context management,
    accessibility tree extraction, and screenshot capture/upload.

engine/
    LangGraph state machine — the planner, executor, evaluator,
    and reporter nodes that drive the autonomous see-think-act loop.

jira/
    Jira REST API v3 client — fetches ticket summary, description,
    and Acceptance Criteria (customfield_10031).

storage/
    S3 upload utilities for screenshots, session videos,
    and HTML audit reports.

Key Modules
-----------
config.py
    Pydantic Settings singleton — the single source of truth for
    all environment-driven configuration.

main.py
    FastAPI application entrypoint with CORS, lifespan events,
    and route registration.
"""
