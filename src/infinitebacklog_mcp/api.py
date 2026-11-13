"""Same-origin JSON API client for Infinite Backlog v2.

The v2 SPA sends a short-lived Keycloak Bearer token with every /api call. This module
reads that header from the SPA's own requests inside this server's Playwright page and
reuses it for in-page fetch() calls. The token stays in memory: it is never logged,
returned from a tool, or written to disk. Every call goes through security.check_api_call.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, Optional
from urllib.parse import urlencode

from playwright.async_api import Page, Request

from .config import IB_ORIGIN, logger
from .security import SecurityError, check_api_call, is_ib_origin

_FETCH_JS = """async ({ method, path, body, token }) => {
  const headers = { 'Accept': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  if (body !== null && body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api' + path, {
    method,
    headers,
    credentials: 'same-origin',
    body: body !== null && body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let data = text;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
  return { ok: response.ok, status: response.status, data, total: response.headers.get('x-total-count') };
}"""

_REFRESH_MARGIN_S = 45.0


class _TokenState:
    __slots__ = ("token", "exp", "page_id")

    def __init__(self) -> None:
        self.token: str = ""
        self.exp: float = 0.0
        self.page_id: int = 0


_state = _TokenState()
_listening: set[int] = set()
_me_cache: dict[int, dict[str, Any]] = {}
_startup_cache: dict[str, Any] = {}


def _jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return float(data.get("exp") or 0)
    except Exception:
        return 0.0


def _token_fresh(page: Page) -> bool:
    return (
        bool(_state.token)
        and _state.page_id == id(page)
        and _state.exp - _REFRESH_MARGIN_S > time.time()
    )


def attach_token_listener(page: Page) -> None:
    """Remember the Bearer header the SPA sends. Safe to call more than once per page."""
    if getattr(page, "is_http", False) or id(page) in _listening:
        return
    _listening.add(id(page))

    async def capture(request: Request) -> None:
        try:
            if "/api/" not in request.url or not is_ib_origin(request.url):
                return
            header = (await request.all_headers()).get("authorization", "")
        except Exception:
            return
        if header.startswith("Bearer "):
            token = header[7:].strip()
            if token and token != _state.token:
                _state.token = token
                _state.exp = _jwt_exp(token) or (time.time() + 240)
                _state.page_id = id(page)

    page.on("request", lambda req: asyncio.ensure_future(capture(req)))


def forget_session() -> None:
    _state.token = ""
    _state.exp = 0.0
    _state.page_id = 0
    _listening.clear()
    _me_cache.clear()


async def _wait_for_token(page: Page, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _token_fresh(page):
            return True
        await asyncio.sleep(0.2)
    return _token_fresh(page)


async def _refresh_token(page: Page) -> bool:
    """Let the SPA mint a fresh token by (re)loading an IB page."""
    attach_token_listener(page)
    try:
        if is_ib_origin(page.url):
            await page.reload(wait_until="domcontentloaded", timeout=60000)
        else:
            await page.goto(f"{IB_ORIGIN}/", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        logger.info("Page reload for a fresh API token failed")
    return await _wait_for_token(page, 20.0)


async def ensure_token(page: Page) -> bool:
    if getattr(page, "is_http", False):
        return await page.ensure_fresh_async()
    attach_token_listener(page)
    if _token_fresh(page):
        return True
    if is_ib_origin(page.url) and await _wait_for_token(page, 1.5):
        return True
    return await _refresh_token(page)


def build_path(path: str, params: Optional[dict[str, Any]] = None) -> str:
    """Append params; list values become key[]=a&key[]=b like the SPA's axios serializer."""
    if not params:
        return path
    pairs: list[tuple[str, Any]] = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            pairs.extend((f"{key}[]", item) for item in value)
        elif isinstance(value, bool):
            pairs.append((key, "true" if value else "false"))
        else:
            pairs.append((key, value))
    if not pairs:
        return path
    sep = "&" if "?" in path else "?"
    return path + sep + urlencode(pairs)


async def _evaluate(page: Page, args: dict[str, Any]) -> Any:
    """Run the in-page fetch. Retries once if the page was mid-navigation; a closed
    window becomes a clean error (the next tool call opens a new one)."""
    idempotent = str(args.get("method") or "GET").upper() in ("GET", "PUT", "DELETE")
    for attempt in (1, 2):
        try:
            return await page.evaluate(_FETCH_JS, args)
        except Exception as exc:
            text = str(exc)
            if page.is_closed() or "has been closed" in text:
                raise SecurityError(
                    "browser_closed", "The browser window closed during the call. Run the tool again."
                ) from None
            navigating = "context was destroyed" in text or "navigat" in text.lower()
            network = "Failed to fetch" in text or "NetworkError" in text
            if attempt == 1 and (navigating or (network and idempotent)):
                await asyncio.sleep(1.0)
                continue
            if network or navigating:
                # POST/PATCH are not retried, so a create is never sent twice.
                return {"ok": False, "status": 0, "data": "network_error"}
            raise
    return None


async def ib_api(
    page: Page,
    method: str,
    path: str,
    body: Any = None,
    params: Optional[dict[str, Any]] = None,
    *,
    auth: bool = True,
) -> dict[str, Any]:
    """Call /api{path} from inside the page. Returns {ok, status, data, total}."""
    verb, safe_path = check_api_call(method, build_path(path, params))
    if getattr(page, "is_http", False):
        return await page.api_async(verb, safe_path, body, auth=auth)
    if not is_ib_origin(page.url):
        await page.goto(f"{IB_ORIGIN}/", wait_until="domcontentloaded", timeout=60000)
    token = ""
    if auth:
        if await ensure_token(page):
            token = _state.token
    result = await _evaluate(page, {"method": verb, "path": safe_path, "body": body, "token": token})
    if auth and isinstance(result, dict) and result.get("status") == 401:
        _state.exp = 0.0
        if await _refresh_token(page):
            result = await _evaluate(
                page, {"method": verb, "path": safe_path, "body": body, "token": _state.token}
            )
    if not isinstance(result, dict):
        return {"ok": False, "status": 0, "data": result}
    return result


def api_error(result: dict[str, Any], action: str) -> dict[str, Any]:
    """Compact error payload for a failed API call. Never includes headers or tokens."""
    status = result.get("status")
    data = result.get("data")
    errors = data.get("errors") if isinstance(data, dict) else None
    codes = [e.get("code") for e in errors or [] if isinstance(e, dict)]
    out: dict[str, Any] = {"error": "api_error", "action": action, "status": status}
    if status == 401:
        out["error"] = "not_logged_in"
        out["hint"] = "Sign in once: call login, or open_site with headless=false and sign in."
    elif status == 403 and "FORBIDDEN" in codes:
        out["error"] = "feature_locked"
        out["hint"] = "Infinite Backlog refused this for the signed-in account's role (often a supporter feature)."
    if errors:
        out["details"] = [
            {k: e.get(k) for k in ("code", "property", "message") if e.get(k)}
            for e in errors
            if isinstance(e, dict)
        ]
    elif data not in (None, ""):
        out["details"] = data if isinstance(data, (dict, list)) else str(data)[:300]
    return out


async def current_user(page: Page, *, refresh: bool = False) -> dict[str, Any] | None:
    """The signed-in user as {id, username, settings}, or None when signed out."""
    if not await ensure_token(page):
        return None
    if not refresh and _me_cache.get(id(page)):
        return _me_cache[id(page)]
    result = await ib_api(page, "GET", "/users/me/complete")
    data = result.get("data")
    if not result.get("ok") or not isinstance(data, dict) or not data.get("id"):
        return None
    me = {
        "id": int(data["id"]),
        "username": str(data.get("username") or ""),
        "review_language": ((data.get("settings") or {}).get("preferences") or {}).get(
            "review_language"
        )
        or "en",
        "currency": data.get("currency"),
    }
    _me_cache[id(page)] = me
    return me


async def startup(page: Page) -> dict[str, Any]:
    if _startup_cache:
        return _startup_cache
    result = await ib_api(page, "GET", "/startup", auth=False)
    if result.get("ok") and isinstance(result.get("data"), dict):
        _startup_cache.update(result["data"])
    return _startup_cache


async def platforms(page: Page) -> list[dict[str, Any]]:
    data = await startup(page)
    return [p for p in data.get("platforms") or [] if isinstance(p, dict)]


def _first(data: Any) -> Any:
    if isinstance(data, list):
        return data[0] if data else None
    return data


async def game_by_slug(page: Page, slug: str, *, full: bool = False) -> dict[str, Any] | None:
    result = await ib_api(
        page,
        "GET",
        f"/games/slug/{slug}",
        params={"expand": "full"} if full else None,
        auth=True,
    )
    game = _first(result.get("data")) if result.get("ok") else None
    return game if isinstance(game, dict) and game.get("id") else None


async def collection_rows(page: Page, user_id: int, game_id: int) -> list[dict[str, Any]]:
    result = await ib_api(
        page, "GET", "/user_collections", params={"user_id": user_id, "game_id": game_id}
    )
    data = result.get("data")
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


async def related_games(page: Page, game_id: int) -> list[dict[str, Any]]:
    result = await ib_api(
        page,
        "GET",
        f"/games/{int(game_id)}/categories",
        params={"category": list(range(15))},
        auth=False,
    )
    data = result.get("data")
    return [g for g in data if isinstance(g, dict)] if isinstance(data, list) else []


async def save_rows(page: Page, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Create or update collection rows (a row with an id is an update), like the SPA."""
    return await ib_api(page, "POST", "/user_collections/bulk", body=rows)


def require_user_error() -> dict[str, Any]:
    return {
        "error": "not_logged_in",
        "hint": "Sign in once: call login (uses IB_USERNAME/IB_PASSWORD), or open_site with headless=false and sign in.",
    }


__all__ = [
    "SecurityError",
    "api_error",
    "attach_token_listener",
    "build_path",
    "collection_rows",
    "current_user",
    "ensure_token",
    "forget_session",
    "game_by_slug",
    "ib_api",
    "platforms",
    "related_games",
    "require_user_error",
    "save_rows",
    "startup",
]
