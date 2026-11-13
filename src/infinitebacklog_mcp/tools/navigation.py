"""MCP tools: browser choice and navigation."""
from __future__ import annotations

from .. import browser as browser_mod
from ..browser import _close_browser, _ensure_browser, _goto_ib, locked_tool
from ..normalize import _dumps
from ..security import ib_url_from_path


async def choose_browser(choice: str = "", path: str = "") -> str:
    """Pick the browser this server may use. Call it without arguments to list the options, then pass the id the USER picked; never choose for them.

    Options: an already-open browser with a local debug port (uses its real profile, one new tab),
    a detected Chromium-based browser started with this server's private profile, Playwright's
    bundled Chromium, or "other" with the path of another Chromium-based browser.
    Changing the choice closes the current session first. Nothing opens until the next tool call.
    """
    if not (choice or "").strip():
        found = await browser_mod.list_choices()
        return _dumps(
            {
                "current": browser_mod.chosen_browser(),
                "choices": [c.public() for c in found]
                + [{"id": "other", "kind": "launch", "label": "Another Chromium-based browser (pass its path)"}],
                "hint": "Ask the user which one to use, then call choose_browser with that id.",
            }
        )
    if not browser_mod._offered and choice.strip() != "other":
        await browser_mod.list_choices()
    previous = browser_mod.chosen_browser()
    picked = browser_mod.set_choice(choice, path)
    if previous and previous != picked.public():
        await _close_browser()
    return _dumps({"ok": True, "browser": picked.public(), "hint": "The browser opens on the next tool call."})


async def open_site(path: str = "/", wait_ms: int = 2000, headless: bool | None = None) -> str:
    """Open a page on infinitebacklog.net in this server's browser window.

    Asks which browser to use first if none was chosen. The window is visible by default
    (Infinite Backlog renders blank in headless mode). Sign in once there; later calls reuse it.
    """
    ib_url_from_path(path)
    page = await _ensure_browser(headless=headless)
    if browser_mod.is_http_mode():
        return _dumps({"error": "not_in_http_mode", "hint": "HTTP mode has no browser window. Call choose_browser to switch to a browser mode."})
    await _goto_ib(page, path, wait_ms)
    title = await page.title()
    return f"Opened {page.url}\nTitle: {title}\n{browser_mod.session_details()}"


async def current_url() -> str:
    """Return the current URL, the page title and which browser is in use."""
    page = await _ensure_browser()
    if browser_mod.is_http_mode():
        return browser_mod.session_details()
    title = await page.title()
    return f"URL: {page.url}\nTitle: {title}\n{browser_mod.session_details()}"


async def close_browser() -> str:
    """Close this server's window. A browser it attached to keeps running; only its own tab closes."""
    await _close_browser()
    return "Browser session closed."


def register(mcp) -> None:
    mcp.tool()(locked_tool(choose_browser))
    mcp.tool()(locked_tool(open_site))
    mcp.tool()(locked_tool(current_url))
    mcp.tool()(locked_tool(close_browser))
