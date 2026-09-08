"""
vQA — LLM Provider Package
============================
Module: backend/llm/__init__.py

Exports the ``get_llm()`` factory function for provider-agnostic
LLM client creation.

Usage
-----
    from backend.llm import get_llm

    llm = get_llm("planner")          # Uses configured provider
    llm = get_llm("parser", max_tokens=2048)
"""

from backend.llm.provider import get_llm  # noqa: F401
