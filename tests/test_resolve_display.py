import os
from unittest.mock import patch
from backend.browser.context import resolve_display


def test_resolve_display_vqa_display_override():
    """Test that VQA_DISPLAY environment variable overrides everything else."""
    env = {}
    with patch.dict(os.environ, {"VQA_DISPLAY": ":12"}):
        resolve_display(env)
    assert env.get("DISPLAY") == ":12"


def test_resolve_display_interactive_mode_default():
    """Test that DISPLAY defaults to :99 in interactive mode when unset."""
    env = {}
    with patch.dict(os.environ, {"VQA_MODE": "interactive"}, clear=True):
        resolve_display(env)
    assert env.get("DISPLAY") == ":99"


def test_resolve_display_interactive_mode_retains_existing():
    """Test that pre-existing DISPLAY inside env is not clobbered in interactive mode."""
    env = {"DISPLAY": "host.docker.internal:0"}
    with patch.dict(os.environ, {"VQA_MODE": "interactive"}, clear=True):
        resolve_display(env)
    assert env.get("DISPLAY") == "host.docker.internal:0"


def test_resolve_display_headless_mode_no_default():
    """Test that display default is NOT set if VQA_MODE is not interactive."""
    env = {}
    with patch.dict(os.environ, {"VQA_MODE": "headless"}, clear=True):
        resolve_display(env)
    assert "DISPLAY" not in env
