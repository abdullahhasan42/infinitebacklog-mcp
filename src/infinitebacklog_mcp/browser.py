"""Browser lifecycle for the tools.

No browser is opened or attached until the user has picked one (MCP elicitation, the
choose_browser tool, or an IB_BROWSER / IB_BROWSER_PATH pre-approval). Launched browsers
always use this server's own profile under .playwright/; an attached browser gets one new
tab and nothing else is read. Paths are never reported, only executable file names.
"""
from __future__ import annotations

import asyncio
import atexit
import contextvars
import functools
import inspect
import os
from typing import Any, Literal, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .browsers import Candidate, candidates, custom_candidate, profile_name
from .config import IB_ORIGIN, default_headless, load_project_env, logger, playwright_profile_dir, viewport
from .security import SecurityError, chromium_launch_args, clamp_wait_ms, ib_url_from_path, is_ib_origin

_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_page: Optional[Page] = None
_playwright = None
_headless_mode: Optional[bool] = None
_attached: bool = False
_opened_page: bool = False
_login_result: str = ""
_tool_lock = asyncio.Lock()

_choice: Optional[Candidate] = None
_offered: dict[str, Candidate] = {}
_request_ctx: contextvars.ContextVar[Any] = contextvars.ContextVar("ib_request_ctx", default=None)

_SLUG_ARGS = ("slug", "parent_slug", "game_slug")


class BrowserChoiceRequired(SecurityError):
    """Raised before any browser opens when the user has not picked one yet."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("browser_choice_required", str(payload.get("hint") or ""))
        self.payload = payload


# --- tool wrapper ----------------------------------------------------------


def _validate_slugs(fn, args, kwargs) -> None:
    """Reject a bad slug before the browser starts. Empty slugs are left to the tool."""
    from .pages import clean_slug

    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
    except TypeError:
        return
    for name in _SLUG_ARGS:
        value = bound.arguments.get(name)
        if isinstance(value, str) and value.strip():
            clean_slug(value)


def locked_tool(fn):
    """Serialize tool bodies, validate slugs early, accept the MCP Context, return JSON errors."""
    from mcp.server.mcpserver import Context

    from .normalize import _dumps

    @functools.wraps(fn)
    async def wrapper(*args, ctx: Optional[Context] = None, **kwargs):
        try:
            _validate_slugs(fn, args, kwargs)
        except SecurityError as exc:
            return _dumps({"error": exc.code, "hint": str(exc)})
        token = _request_ctx.set(ctx)
        try:
            async with _tool_lock:
                try:
                    return await fn(*args, **kwargs)
                except BrowserChoiceRequired as exc:
                    return _dumps(exc.payload)
                except SecurityError as exc:
                    return _dumps({"error": exc.code, "hint": str(exc)})
                except ValueError as exc:
                    return _dumps({"error": "invalid_argument", "hint": str(exc)})
        finally:
            _request_ctx.reset(token)

    sig = inspect.signature(fn)
    params = list(sig.parameters.values()) + [
        inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Optional[Context])
    ]
    wrapper.__signature__ = sig.replace(parameters=params)
    wrapper.__annotations__ = {**getattr(fn, "__annotations__", {}), "ctx": Optional[Context]}
    return wrapper


# --- origin guards ---------------------------------------------------------


async def recover_off_origin(page: Page) -> None:
    """If the page left IB, try to return, then raise."""
    if is_ib_origin(page.url):
        return
    try:
        await page.go_back(wait_until="domcontentloaded")
    except Exception:
        pass
    if is_ib_origin(page.url):
        raise SecurityError("off_origin", "Navigation left infinitebacklog.net; returned to the previous page.")
    try:
        await page.goto(f"{IB_ORIGIN}/", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
    if is_ib_origin(page.url):
        raise SecurityError("off_origin", "Navigation left infinitebacklog.net; returned to the home page.")
    raise SecurityError("off_origin", "Navigation left infinitebacklog.net.")


async def require_ib_page(page: Page) -> None:
    if not is_ib_origin(page.url):
        raise SecurityError("off_origin", "Current page is not infinitebacklog.net. Call open_site first.")


# --- choosing a browser ----------------------------------------------------


def chosen_browser() -> Optional[dict[str, str]]:
    return _choice.public() if _choice else None


def is_http_mode() -> bool:
    return bool(_choice and _choice.kind == "http")


def session_details() -> str:
    """Status lines for open_site and current_url. No paths, cookies or endpoints."""
    if is_http_mode():
        return "mode=http (no browser)"
    lines = [f"mode={'attached' if _attached else 'launched'}"]
    if _choice:
        lines.append(f"browser={_choice.label}")
    if not _attached:
        lines.append(f"headless={_headless_mode}")
    return "\n".join(lines)


async def list_choices() -> list[Candidate]:
    global _offered
    found = await asyncio.to_thread(candidates)
    _offered = {c.id: c for c in found}
    return found


def _choice_payload(found: list[Candidate]) -> dict[str, Any]:
    return {
        "error": "browser_choice_required",
        "hint": (
            "No browser has been opened. Ask the user which one to use, then call "
            "choose_browser with their answer. Do not pick for them."
        ),
        "choices": [c.public() for c in found]
        + [{"id": "other", "kind": "launch", "label": "Another Chromium-based browser (pass its path)"}],
    }


def set_choice(choice: str, path: str = "") -> Candidate:
    """Record the user's pick. Raises ValueError for an unknown id or a bad path."""
    global _choice
    key = (choice or "").strip()
    if key == "other":
        picked = custom_candidate(path)
    elif key in _offered:
        picked = _offered[key]
    else:
        raise ValueError(f"Unknown browser choice {key!r}. Call choose_browser without a choice to list them.")
    _choice = picked
    return picked


def _pre_approved(found: list[Candidate]) -> Optional[Candidate]:
    """IB_BROWSER / IB_BROWSER_PATH let a user approve a browser ahead of time."""
    path = (os.environ.get("IB_BROWSER_PATH") or "").strip()
    if path:
        return custom_candidate(path)
    wanted = (os.environ.get("IB_BROWSER") or "").strip().lower()
    if not wanted:
        return None
    for cand in found:
        if wanted == "bundled" and cand.kind == "bundled":
            return cand
        if wanted == "attach" and cand.kind == "attach":
            return cand
        if wanted == "http" and cand.kind == "http":
            return cand
        if wanted == "default" and cand.kind == "launch" and "default browser" in cand.label:
            return cand
    raise SecurityError("browser_unavailable", f"IB_BROWSER={wanted} is not available on this machine.")


async def _ask_user(found: list[Candidate]) -> Optional[Candidate]:
    """Ask through MCP elicitation. None when the client can't ask."""
    ctx = _request_ctx.get()
    if ctx is None:
        return None
    from pydantic import Field, create_model

    ids = tuple([c.id for c in found] + ["other"])
    lines = "\n".join(f"- {c.id}: {c.label}" for c in found)
    schema = create_model(
        "BrowserChoice",
        choice=(Literal[ids], Field(description="Which browser to use")),  # type: ignore[valid-type]
        path=(str, Field(default="", description="Only for 'other': the browser executable path")),
    )
    message = (
        "Infinite Backlog MCP needs a browser to sign in and work on your account. Pick one:\n"
        f"{lines}\n- other: another Chromium-based browser (enter its path)"
    )
    try:
        result = await ctx.elicit(message=message, schema=schema)
    except Exception:
        return None
    if getattr(result, "action", "") != "accept":
        raise SecurityError("browser_not_approved", "No browser was approved, so nothing was opened.")
    data = result.data
    return set_choice(str(data.choice), str(getattr(data, "path", "") or ""))


async def _resolve_choice() -> Candidate:
    global _choice
    if _choice:
        return _choice
    found = await list_choices()
    pre = _pre_approved(found)
    if pre:
        _choice = pre
        return pre
    asked = await _ask_user(found)
    if asked:
        return asked
    raise BrowserChoiceRequired(_choice_payload(found))


# --- lifecycle -------------------------------------------------------------


def _reset_session_state() -> None:
    global _browser, _context, _page, _playwright, _headless_mode, _attached, _opened_page, _login_result
    _page = _context = _browser = _playwright = None
    _headless_mode = None
    _attached = False
    _opened_page = False
    _login_result = ""
    from .api import forget_session

    forget_session()


async def _launch(cand: Candidate, headless: bool) -> Page:
    global _browser, _context, _page, _playwright, _headless_mode, _attached, _opened_page
    if _playwright is None:
        _playwright = await async_playwright().start()
    options: dict[str, Any] = {
        "user_data_dir": str(playwright_profile_dir(profile_name(cand))),
        "headless": headless,
        "viewport": viewport(),
        "args": chromium_launch_args(),
    }
    if cand.kind == "launch" and cand.exe:
        options["executable_path"] = cand.exe
    try:
        _context = await _playwright.chromium.launch_persistent_context(**options)
    except Exception as exc:
        raise SecurityError(
            "browser_start_failed",
            "The chosen browser did not start. Close a leftover window from this server, "
            "or call choose_browser to pick another one.",
        ) from exc
    _browser = _context.browser
    _headless_mode = headless
    _attached = False
    _opened_page = True
    pages = [p for p in _context.pages if not p.is_closed()]
    _page = pages[0] if pages else await _context.new_page()
    logger.info("Browser started: %s, headless=%s", cand.label.split(" ")[0], headless)
    return _page


async def _attach(cand: Candidate) -> Page:
    global _browser, _context, _page, _playwright, _headless_mode, _attached, _opened_page
    if _playwright is None:
        _playwright = await async_playwright().start()
    try:
        _browser = await asyncio.wait_for(_playwright.chromium.connect_over_cdp(cand.endpoint), timeout=20)
    except Exception as exc:
        raise SecurityError(
            "browser_attach_failed",
            "Could not attach to the open browser. Call choose_browser to pick another option.",
        ) from exc
    _context = _browser.contexts[0] if _browser.contexts else await _browser.new_context()
    _page = await _context.new_page()
    _attached = True
    _opened_page = True
    _headless_mode = False
    logger.info("Attached to an open browser (one new tab)")
    return _page


async def _http_session():
    """Browserless mode: one in-memory HTTP session; signs in from .env when both values are set."""
    global _page
    from .http_auth import HttpSession

    _page = HttpSession()
    await _maybe_login(_page)
    return _page


async def _maybe_login(page: Page) -> None:
    """Use .env credentials when both are set. Skip when either is missing."""
    global _login_result
    from .login import credentials, login_from_env

    if _login_result in {"ok", "failed"}:
        return
    username, password = credentials()
    if not username or not password:
        return
    result = await login_from_env(page)
    _login_result = "ok" if result.get("ok") else "failed"
    if not result.get("ok"):
        logger.info("Sign-in did not complete")


async def _ensure_browser(headless: bool | None = None) -> Page:
    """The page every tool works in. Opens nothing until the user has chosen a browser."""
    load_project_env()
    if headless is None:
        headless = default_headless()
    if _page is not None and not _page.is_closed():
        if not _attached and headless is False and _headless_mode is True:
            await _close_browser()
        else:
            from .api import attach_token_listener

            attach_token_listener(_page)
            await _maybe_login(_page)
            return _page
    cand = await _resolve_choice()
    if cand.kind == "http":
        return await _http_session()
    page = await (_attach(cand) if cand.kind == "attach" else _launch(cand, headless))
    from .api import attach_token_listener

    attach_token_listener(page)
    await _maybe_login(page)
    return page


async def _close_browser() -> None:
    """Close what this server opened. An attached browser keeps running; only our tab closes."""
    had_session = _browser is not None or _playwright is not None or getattr(_page, "is_http", False)
    page, context, browser, playwright, attached = _page, _context, _browser, _playwright, _attached
    if getattr(page, "is_http", False):
        page.forget()
        _reset_session_state()
        logger.info("HTTP session closed")
        return
    try:
        if page is not None and not page.is_closed():
            await page.close()
    except Exception:
        logger.info("Could not close this server's tab")
    if not attached and context is not None:
        try:
            await context.close()
        except Exception:
            pass
    if browser is not None:
        try:
            await browser.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            await asyncio.wait_for(playwright.stop(), timeout=3)
        except Exception:
            pass
    _reset_session_state()
    if had_session:
        logger.info("Browser session closed")


# --- navigation helpers ----------------------------------------------------


async def _goto_ib(page: Page, path: str, wait_ms: int = 2000) -> None:
    wait_ms = clamp_wait_ms(wait_ms)
    await page.goto(ib_url_from_path(path), wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(wait_ms)
    try:
        await page.wait_for_selector("#app", timeout=min(max(wait_ms, 2000), 12000))
    except Exception:
        pass
    await _wait_spa_text(page, timeout_ms=min(max(wait_ms, 2000), 8000))
    await recover_off_origin(page)


async def _wait_spa_text(page: Page, min_chars: int = 400, timeout_ms: int = 8000) -> None:
    """Wait until the Vue app has real content (an h1, the search box, or enough text)."""
    try:
        await page.wait_for_function(
            """(min) => {
              const t = (document.body && document.body.innerText || '').trim();
              if (t.length > min) return true;
              const h1 = document.querySelector('h1');
              if (h1 && (h1.innerText || '').trim()) return true;
              return !!document.querySelector('#search, #game-search');
            }""",
            arg=int(min_chars),
            timeout=timeout_ms,
        )
    except Exception:
        pass


def _sync_close_browser() -> None:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_close_browser())
        else:
            loop.run_until_complete(_close_browser())
    except Exception:
        pass


atexit.register(_sync_close_browser)
