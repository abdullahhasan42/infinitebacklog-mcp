"""MCP tools: your wishlist (games you want, with optional notes, pre-order and favourite flags)."""
from __future__ import annotations

from typing import Any

from ..api import api_error, current_user, ib_api, require_user_error
from ..browser import _ensure_browser, locked_tool
from ..normalize import _dumps, slim_game
from ..pages import game_context


def _slim_wish(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **(slim_game(row.get("game")) or {}),
        "wishlist_id": row.get("id"),
        "notes": row.get("notes"),
        "preorder": row.get("preorder"),
        "favourite": row.get("favourite"),
    }


async def _wish_row(page, user_id: int, game_id: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(row or None, error). The row is None when the game is not on the wishlist."""
    result = await ib_api(page, "GET", "/user_wishlists", params={"user_id": user_id, "game_id": game_id})
    if not result.get("ok"):
        return None, api_error(result, "get_wishlist_row")
    data = result.get("data")
    rows = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    return (rows[0] if rows else None), None


async def list_wishlist(limit: int = 25, offset: int = 0) -> str:
    """List the games on your wishlist with notes, pre-order and favourite flags. Read-only."""
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    params: dict[str, Any] = {
        "user_id": me["id"],
        "limit": max(1, min(int(limit or 25), 100)),
        "offset": max(0, int(offset or 0)),
    }
    result = await ib_api(page, "GET", "/user_wishlists", params=params)
    if not result.get("ok"):
        return _dumps(api_error(result, "list_wishlist"))
    rows = [r for r in result.get("data") or [] if isinstance(r, dict)]
    return _dumps(
        {
            "user": me["username"],
            "count": len(rows),
            "games": [_slim_wish(r) for r in rows],
        },
        limit=40000,
    )


async def add_to_wishlist(slug: str, notes: str = "", preorder: str = "") -> str:
    """Add a game to your wishlist. Optional notes and preorder ("true"/"false"; empty keeps the current value), applied also when the game is already on it."""
    pre = (preorder or "").strip().lower()
    if pre not in ("", "true", "false"):
        return _dumps({"error": "invalid_flag", "hint": "preorder takes true or false."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    me, game, gid = ctx["user"], ctx["game"], ctx["game_id"]
    row, err = await _wish_row(page, me["id"], gid)
    if err:
        return _dumps(err)
    status = "already_on_wishlist" if row else "added"
    if row is None:
        made = await ib_api(page, "POST", "/user_wishlists", body={"game_id": gid})
        if not made.get("ok"):
            return _dumps(api_error(made, "add_to_wishlist"))
    if row is None or notes or pre:
        row, err = await _wish_row(page, me["id"], gid)
        if err:
            return _dumps(err)
        if not row:
            return _dumps({"error": "wishlist_row_missing", "slug": ctx["slug"]})
    final_notes = row.get("notes")
    final_preorder = row.get("preorder")
    if notes or pre:
        final_notes = notes or row.get("notes")
        final_preorder = (pre == "true") if pre else bool(row.get("preorder"))
        saved = await ib_api(
            page,
            "PUT",
            f"/user_wishlists/{int(row['id'])}",
            body={**row, "notes": final_notes, "preorder": final_preorder},
        )
        if not saved.get("ok"):
            return _dumps(api_error(saved, "add_to_wishlist"))
    return _dumps(
        {
            "ok": True,
            "status": status,
            "game": slim_game(game),
            "wishlist": {"id": row.get("id"), "notes": final_notes, "preorder": final_preorder},
        }
    )


async def remove_from_wishlist(slug: str, confirm: bool = False) -> str:
    """Remove a game from your wishlist. Needs confirm=true."""
    if not confirm:
        return _dumps({"error": "confirm_required", "hint": "Pass confirm=true to remove this game from your wishlist."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    result = await ib_api(page, "DELETE", f"/user_wishlists/game/{int(ctx['game_id'])}")
    if not result.get("ok"):
        return _dumps(api_error(result, "remove_from_wishlist"))
    return _dumps({"ok": True, "status": "removed", "game": slim_game(ctx["game"])})


def register(mcp) -> None:
    mcp.tool()(locked_tool(list_wishlist))
    mcp.tool()(locked_tool(add_to_wishlist))
    mcp.tool()(locked_tool(remove_from_wishlist))
