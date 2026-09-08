"""
vQA Browser — Playwright Infrastructure Package
=================================================

This package wraps Playwright to provide browser automation
primitives used by the LangGraph engine nodes.

Modules
-------
context.py
    ``BrowserContextManager`` — creates and manages Playwright
    browser contexts with video recording (``record_video_dir``),
    viewport configuration, and headless/interactive mode support.

accessibility.py
    Extracts the ARIA accessibility tree from a Playwright page
    using ``page.accessibility.snapshot()``.  The resulting tree
    is sent alongside screenshots to Claude 3.5 Sonnet for
    dual-grounded (visual + structural) reasoning.

screenshot.py
    Captures full-page screenshots as base64-encoded PNGs and
    uploads them to S3.  Every screenshot is logged with a
    timestamp and step index for the audit report.
"""
