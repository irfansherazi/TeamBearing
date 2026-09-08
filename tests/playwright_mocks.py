"""
vQA — Shared Playwright Mocks for Unit Testing
==============================================
Module: tests/playwright_mocks.py

Centralized mock objects and factories for Playwright components (Page, Browser,
Context).  Allows unit testing of engine nodes without spawning real browsers.

Patterns
--------
  - Uses ``unittest.mock.AsyncMock`` for all awaitable Playwright methods.
  - Uses ``unittest.mock.MagicMock`` for synchronous methods (locator, etc).
"""

from unittest.mock import AsyncMock, MagicMock


def mock_page(
    *,
    url: str = "https://two-test.vcreative.net",
    content: str = "<html><body>vQA Test Page</body></html>",
    locator_visible: bool = True,
    locator_count: int = 1,
) -> MagicMock:
    """
    Construct a Playwright Page mock with common async methods pre-configured.

    Args
    ----
    url : str
        The value returned by ``page.url``.
    content : str
        The value returned by ``page.content()``.
    locator_visible : bool
        Default return value for ``page.locator(...).is_visible()``.
    locator_count : int
        Default return value for ``page.locator(...).count()``.

    Returns
    -------
    MagicMock
        A mock object behaving like a Playwright Page.
    """
    page = MagicMock()
    page.url = url
    page.content = AsyncMock(return_value=content)
    page.goto = AsyncMock(return_value=None)
    page.wait_for_load_state = AsyncMock(return_value=None)
    page.screenshot = AsyncMock(return_value=b"fake-png-bytes")
    page.evaluate = AsyncMock(return_value=None)
    page.close = AsyncMock(return_value=None)

    # Locator mock
    locator = MagicMock()
    locator.is_visible = AsyncMock(return_value=locator_visible)
    locator.count = AsyncMock(return_value=locator_count)
    locator.first = MagicMock(return_value=locator)
    locator.click = AsyncMock(return_value=None)
    locator.fill = AsyncMock(return_value=None)
    locator.select_option = AsyncMock(return_value=None)
    locator.press = AsyncMock(return_value=None)
    locator.inner_text = AsyncMock(return_value="Mock Element Text")
    locator.get_attribute = AsyncMock(return_value=None)

    page.locator = MagicMock(return_value=locator)
    page.get_by_role = MagicMock(return_value=locator)
    page.get_by_label = MagicMock(return_value=locator)
    page.get_by_text = MagicMock(return_value=locator)
    page.get_by_placeholder = MagicMock(return_value=locator)
    page.get_by_test_id = MagicMock(return_value=locator)

    return page


def mock_browser_context(page: MagicMock | None = None) -> MagicMock:
    """Mock for Playwright BrowserContext."""
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page or mock_page())
    context.close = AsyncMock(return_value=None)
    context.clear_cookies = AsyncMock(return_value=None)
    context.add_cookies = AsyncMock(return_value=None)
    context.tracing.start = AsyncMock(return_value=None)
    context.tracing.stop = AsyncMock(return_value=None)
    return context


def mock_browser(context: MagicMock | None = None) -> MagicMock:
    """Mock for Playwright Browser."""
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context or mock_browser_context())
    browser.close = AsyncMock(return_value=None)
    browser.is_connected = MagicMock(return_value=True)
    return browser
