"""MCP tools: your custom game lists. Lists can be public, so they stay drafts unless publish=true."""
from __future__ import annotations

from typing import Any

from ..api import api_error, current_user, ib_api, require_user_error
from ..browser import _ensure_browser, locked_tool
from ..normalize import _dumps, text_to_html
from ..pages import resolve_game
from .tags import _names

TITLE_MAX = 100
LIST_URL = "https://infinitebacklog.net/lists/{}"


def list_body(
    title,
    description_html,
    games,
    *,
    ranked=False,
    publish=False,
    spoilers=False,
    mature_content=False,
) -> dict[str, Any]:
    """The JSON body the SPA posts for a personal list. Drafts by default (published=false)."""
    return {
        "banner": None,
        "description": description_html,
        "display": "grid",
        "games": ranked_games(games),
        "list_template_id": None,
        "mature_content": bool(mature_content),
        "post_feed": False,
        "published": bool(publish),
        "ranked": bool(ranked),
        "sorting": "list",
        "sorting_order": "asc",
        "spoilers": bool(spoilers),
        "tags": [],
        "title": title,
        "type": "personal",
    }


def ranked_games(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The API needs a 1-based rank on every list entry, in list order."""
    return [{**g, "rank": i} for i, g in enumerate(games, start=1)]


def _list_id(value: Any) -> int | None:
    raw = str(value if value is not None else "").strip()
    return int(raw) if raw.isdigit() else None


def _flag(value: str) -> bool | None:
    raw = (value or "").strip().lower()
    if raw == "true":
        return True
    if raw == "false":
        return False
    return None


def _slim_list(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "description": data.get("description"),
        "published": data.get("published"),
        "ranked": data.get("ranked"),
        "type": data.get("type"),
        "games": [
            {"id": g.get("id"), "name": g.get("name"), "slug": g.get("slug")}
            for g in data.get("games") or []
            if isinstance(g, dict)
        ],
        "user": (data.get("user") or {}).get("username"),
    }


async def _resolve_games(page, slugs: list[str]) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    items: list[dict[str, Any]] = []
    for slug in slugs:
        found = await resolve_game(page, slug)
        if found.get("error"):
            return None, found
        game = found["game"]
        if any(str(i["id"]) == str(game.get("id")) for i in items):
            continue
        items.append({"id": game.get("id"), "name": game.get("name"), "slug": game.get("slug")})
    return items, None


async def _owned_list(page, lid: int, action: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(list, error). Only the signed-in user's own lists pass."""
    me = await current_user(page)
    if not me:
        return None, require_user_error()
    got = await ib_api(page, "GET", f"/lists/{lid}")
    if not got.get("ok"):
        return None, api_error(got, action)
    data = got.get("data") if isinstance(got.get("data"), dict) else None
    if not data:
        return None, {"error": "list_not_found", "list_id": lid}
    if str((data.get("user") or {}).get("id")) != str(me["id"]):
        return None, {"error": "not_your_list", "list_id": lid}
    return data, None


async def list_my_lists(limit: int = 25, offset: int = 0) -> str:
    """List your custom game lists (id, title, published, number of games, last update). Read-only."""
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    params: dict[str, Any] = {
        "user_id": me["id"],
        "limit": max(1, min(int(limit or 25), 100)),
        "offset": max(0, int(offset or 0)),
    }
    result = await ib_api(page, "GET", "/lists", params=params)
    if not result.get("ok"):
        return _dumps(api_error(result, "list_my_lists"))
    rows = [r for r in result.get("data") or [] if isinstance(r, dict)]
    return _dumps(
        {
            "user": me["username"],
            "total": result.get("total"),
            "count": len(rows),
            "lists": [
                {
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "published": r.get("published"),
                    "total_games": r.get("total_games"),
                    "updated_at": r.get("updated_at"),
                }
                for r in rows
            ],
        }
    )


async def get_list(list_id: str) -> str:
    """Read one custom list: title, description, published and ranked flags, and its games in order. Read-only."""
    lid = _list_id(list_id)
    if lid is None:
        return _dumps({"error": "invalid_list_id", "hint": "Pass the numeric list id."})
    page = await _ensure_browser()
    result = await ib_api(page, "GET", f"/lists/{lid}")
    if not result.get("ok"):
        return _dumps(api_error(result, "get_list"))
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return _dumps(_slim_list(data))


async def create_list(
    title: str,
    games: str = "",
    description: str = "",
    ranked: bool = False,
    publish: bool = False,
    spoilers: bool = False,
    mature_content: bool = False,
) -> str:
    """Create a custom game list. games: comma-separated game slugs or a JSON array. Saved as a draft unless publish=true (public)."""
    clean = (title or "").strip()
    if not 1 <= len(clean) <= TITLE_MAX:
        return _dumps({"error": "invalid_title", "hint": "Use 1 to 100 characters."})
    slugs = _names(games)
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    items, err = await _resolve_games(page, slugs)
    if err:
        return _dumps(err)
    body = list_body(
        clean,
        text_to_html(description) if (description or "").strip() else "",
        items,
        ranked=ranked,
        publish=publish,
        spoilers=spoilers,
        mature_content=mature_content,
    )
    result = await ib_api(page, "POST", "/lists", body=body)
    if not result.get("ok"):
        return _dumps(api_error(result, "create_list"))
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    lid = data.get("id")
    return _dumps(
        {
            "ok": True,
            "list_id": lid,
            "title": clean,
            "published": bool(publish),
            "games": [i["slug"] for i in items],
            "url": LIST_URL.format(lid),
        }
    )


async def update_list(
    list_id: str,
    title: str = "",
    description: str = "",
    add_games: str = "",
    remove_games: str = "",
    ranked: str = "",
    publish: str = "",
) -> str:
    """Edit your own custom list: title, description, add_games / remove_games (slugs or ids), ranked and publish ("true"/"false"). Only the fields you pass change."""
    lid = _list_id(list_id)
    if lid is None:
        return _dumps({"error": "invalid_list_id", "hint": "Pass the numeric list id."})
    ranked_v = _flag(ranked) if str(ranked or "").strip() else None
    publish_v = _flag(publish) if str(publish or "").strip() else None
    if (ranked and ranked_v is None) or (publish and publish_v is None):
        return _dumps({"error": "invalid_flag", "hint": "ranked and publish take true or false."})
    clean_title = (title or "").strip()
    if clean_title and not 1 <= len(clean_title) <= TITLE_MAX:
        return _dumps({"error": "invalid_title", "hint": "Use 1 to 100 characters."})
    page = await _ensure_browser()
    current, err = await _owned_list(page, lid, "update_list")
    if err:
        return _dumps(err)
    body: dict[str, Any] = dict(current)
    if clean_title:
        body["title"] = clean_title
    if description:
        body["description"] = text_to_html(description)
    if ranked_v is not None:
        body["ranked"] = ranked_v
    if publish_v is not None:
        body["published"] = publish_v
    games = [g for g in current.get("games") or [] if isinstance(g, dict)]
    if add_games:
        items, err = await _resolve_games(page, _names(add_games))
        if err:
            return _dumps(err)
        for item in items:
            if not any(str(g.get("id")) == str(item["id"]) for g in games):
                games.append(item)
    if remove_games:
        drop = {t.casefold() for t in _names(remove_games)}
        games = [
            g
            for g in games
            if str(g.get("id")).casefold() not in drop and str(g.get("slug") or "").casefold() not in drop
        ]
    body["games"] = ranked_games(games)
    body["post_feed"] = False
    result = await ib_api(page, "PUT", f"/lists/{lid}", body=body)
    if not result.get("ok"):
        return _dumps(api_error(result, "update_list"))
    data = result.get("data") if isinstance(result.get("data"), dict) and result["data"].get("id") else body
    return _dumps({"ok": True, "list": _slim_list(data)})


async def delete_list(list_id: str, confirm: bool = False) -> str:
    """Delete one of your custom lists. Needs confirm=true."""
    if not confirm:
        return _dumps({"error": "confirm_required", "hint": "Pass confirm=true to delete this list."})
    lid = _list_id(list_id)
    if lid is None:
        return _dumps({"error": "invalid_list_id", "hint": "Pass the numeric list id."})
    page = await _ensure_browser()
    current, err = await _owned_list(page, lid, "delete_list")
    if err:
        return _dumps(err)
    result = await ib_api(page, "DELETE", f"/lists/{lid}")
    if not result.get("ok"):
        return _dumps(api_error(result, "delete_list"))
    return _dumps({"ok": True, "status": "deleted", "list_id": lid, "title": current.get("title")})


def register(mcp) -> None:
    for fn in (list_my_lists, get_list, create_list, update_list, delete_list):
        mcp.tool()(locked_tool(fn))
