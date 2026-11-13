"""Shared lookups for tools: signed-in user, game, and the caller's collection rows (IB v2 API)."""
from __future__ import annotations

from typing import Any, Optional

from playwright.async_api import Page

from .api import collection_rows, current_user, game_by_slug, require_user_error
from .normalize import slim_collection_row
from .security import (
    SecurityError,
    sanitize_collection_id,
    sanitize_slug,
)


def clean_slug(slug: str) -> str:
    """Accept a slug, /games/{slug}, a game URL, or a /users/{u}/collection/{slug} path."""
    raw = (slug or "").strip().strip("/")
    if "infinitebacklog.net/" in raw:
        raw = raw.split("infinitebacklog.net/", 1)[1].split("?", 1)[0].strip("/")
    parts = [p for p in raw.split("/") if p]
    if "collection" in parts and parts.index("collection") + 1 < len(parts):
        raw = parts[parts.index("collection") + 1]
    elif parts and parts[0] == "games" and len(parts) > 1:
        raw = parts[1]
    return sanitize_slug(raw)


def user_id_from_search(username: str, rows: Any) -> int:
    """Pick the search row whose username matches. Never use the first row."""
    wanted = (username or "").casefold()
    if not wanted or not isinstance(rows, list):
        return 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("username") or "").casefold() != wanted:
            continue
        try:
            return int(row.get("id") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def pick_row(rows: list[dict[str, Any]], collection_id: str) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """(row, error). One row is picked automatically; several need collection_id."""
    cid = sanitize_collection_id(collection_id, allow_empty=True)
    if cid:
        for row in rows:
            if str(row.get("id")) == cid:
                return row, None
        return None, {
            "error": "collection_id_not_found",
            "collection_id": cid,
            "copies": [slim_collection_row(r) for r in rows],
        }
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, {"error": "not_in_collection", "hint": "Add the game first with add_game_to_collection."}
    return None, {
        "error": "collection_id_required",
        "hint": "This game has more than one copy. Pass collection_id.",
        "copies": [slim_collection_row(r) for r in rows],
    }


async def resolve_game(page: Page, slug: str, *, full: bool = False) -> dict[str, Any]:
    safe = clean_slug(slug)
    game = await game_by_slug(page, safe, full=full)
    if not game:
        return {"error": "game_not_found", "slug": safe}
    return {"slug": safe, "game": game, "game_id": int(game["id"])}


async def game_context(
    page: Page,
    slug: str,
    collection_id: str = "",
    *,
    need_row: bool = True,
    full: bool = False,
) -> dict[str, Any]:
    """Resolve user + game + collection rows. Returns a dict with an "error" key on failure."""
    me = await current_user(page)
    if not me:
        return require_user_error()
    found = await resolve_game(page, slug, full=full)
    if found.get("error"):
        return found
    rows = await collection_rows(page, me["id"], found["game_id"])
    ctx: dict[str, Any] = {**found, "user": me, "rows": rows, "row": None}
    if need_row:
        row, err = pick_row(rows, collection_id)
        if err:
            return {**err, "slug": found["slug"]}
        ctx["row"] = row
    return ctx


__all__ = [
    "SecurityError",
    "clean_slug",
    "game_context",
    "pick_row",
    "resolve_game",
    "user_id_from_search",
]
