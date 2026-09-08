import pytest


def test_browser_profile_import():
    """
    AC-TEST-1: Smoke test to confirm that browser_use API hasn't changed its export location
    for BrowserProfile. The current version expects it at browser_use.browser.profile.
    """
    pytest.importorskip("browser_use")
    try:
        from browser_use.browser.profile import BrowserProfile

        assert BrowserProfile is not None
    except ImportError as e:
        pytest.fail(f"browser_use API changed: could not import BrowserProfile. Error: {e}")
