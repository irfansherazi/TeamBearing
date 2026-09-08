"""
vQA API — FastAPI Routes and Schemas Package
=============================================

This package contains the REST and WebSocket API layer.

Modules
-------
routes.py
    Endpoint handlers: ``POST /execute``, ``POST /execute-batch``,
    ``GET /status/{run_id}``, ``GET /health``, ``WebSocket /ws/{run_id}``.

schemas.py
    Pydantic request/response models for all endpoints.
    Provides input validation, serialisation, and auto-generated
    OpenAPI documentation at ``/docs``.
"""
