"""MCP tools: DLC, expansions, packs and add-ons attached to a collection copy."""
from __future__ import annotations

from typing import Any

from ..api import api_error, related_games
from ..browser import _ensure_browser, locked_tool
from ..config import ADDON_CATEGORIES, DLC_CATEGORIES
from ..names import _names_match, _parse_names
from ..normalize import _dumps, category_name, normalize_completion, slim_collection_row, slim_game
from ..pages import game_context
from .collection import _save

_ATTACHABLE = DLC_CATEGORIES | ADDON_CATEGORIES


def _addition_entry(game: dict[str, Any]) -> dict[str, Any]:
    """The addition object the SPA pushes: DLC tracks completion, packs do not."""
    tracked = game.get("category") in DLC_CATEGORIES
    return {"game_id": int(game["id"]), "completion": "notStarted" if tracked else None}


def _match(name: str, candidates: list[dict[str, Any]], parent_title: str) -> list[dict[str, Any]]:
    exact = [c for c in candidates if str(c.get("name") or "").casefold() == name.strip().casefold()]
    if exact:
        return exact
    if name.strip().isdigit():
        return [c for c in candidates if str(c.get("id")) == name.strip()]
    return [c for c in candidates if _names_match(name, str(c.get("name") or ""), parent_title)]


async def list_collection_content_menus(slug: str = "", collection_id: str = "", edit_path: str = "") -> str:
    """For one copy: DLC/expansions and packs/add-ons you already attached, and the ones you can still add. Read-only. (edit_path is accepted for v1 callers: /users/{u}/collection/{slug}/edit?id=N.)"""
    if not slug and edit_path:
        slug = edit_path
        if "id=" in edit_path and not collection_id:
            collection_id = edit_path.split("id=", 1)[1].split("&", 1)[0]
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    row = ctx["row"]
    owned_ids = {a.get("game_id") for a in row.get("additions") or [] if isinstance(a, dict)}
    available: dict[str, list[dict[str, Any]]] = {"dlc": [], "addons": []}
    for game in await related_games(page, ctx["game_id"]):
        cat = game.get("category")
        if cat not in _ATTACHABLE or game.get("id") in owned_ids:
            continue
        bucket = "dlc" if cat in DLC_CATEGORIES else "addons"
        available[bucket].append({**(slim_game(game) or {}), "kind": category_name(cat)})
    copy = slim_collection_row(row) or {}
    return _dumps(
        {
            "game": slim_game(ctx["game"]),
            "collection_id": row.get("id"),
            "owned": copy.get("additions"),
            "available": available,
        }
    )


async def add_game_content(
    parent_slug: str,
    names: str,
    collection_id: str = "",
    completion: str = "",
    platform: str = "",
    digital: bool | None = None,
    wait_ms: int = 0,
) -> str:
    """Attach DLC, expansions, packs or add-ons to a copy you own. names: one title, a JSON array, or one title per line (game ids also work). Matches against the game's related content; already-attached items are skipped. completion (DLC only) sets their completion. platform/digital are ignored (they belong to the parent copy)."""
    del platform, digital, wait_ms
    wanted = _parse_names(names)
    if not wanted:
        return _dumps({"error": "no_names", "hint": "Pass a title, a JSON array, or one title per line."})
    page = await _ensure_browser()
    ctx = await game_context(page, parent_slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    comp = normalize_completion(completion) if completion else None
    if completion and not comp:
        return _dumps({"error": "unknown_completion", "completion": completion})
    row = ctx["row"]
    parent_title = str(ctx["game"].get("name") or "")
    candidates = [g for g in await related_games(page, ctx["game_id"]) if g.get("category") in _ATTACHABLE]
    additions = [a for a in row.get("additions") or [] if isinstance(a, dict)]
    owned_ids = {a.get("game_id") for a in additions}
    report: list[dict[str, Any]] = []
    new_entries: list[dict[str, Any]] = []
    for name in wanted:
        hits = _match(name, candidates, parent_title)
        if not hits:
            report.append({"name": name, "status": "not_found"})
            continue
        if len(hits) > 1 and not any(str(h.get("name")).casefold() == name.casefold() for h in hits):
            report.append({"name": name, "status": "ambiguous", "matches": [slim_game(h) for h in hits[:8]]})
            continue
        game = hits[0]
        if game["id"] in owned_ids:
            report.append({"name": name, "status": "already_owned", "game": slim_game(game)})
            continue
        entry = _addition_entry(game)
        if comp and entry["completion"] is not None:
            entry["completion"] = comp
        new_entries.append(entry)
        owned_ids.add(game["id"])
        report.append({"name": name, "status": "added", "game": slim_game(game), "kind": category_name(game.get("category"))})
    if not new_entries:
        return _dumps({"ok": True, "changed": False, "results": report})
    saved = await _save(page, row, {"additions": additions + new_entries}, "add_game_content")
    return _dumps({**saved, "results": report})


async def remove_game_content(parent_slug: str, names: str, collection_id: str = "", confirm: bool = False) -> str:
    """Detach DLC/packs from a copy. Needs confirm=true. Does not touch the parent copy itself."""
    if not confirm:
        return _dumps({"error": "confirm_required", "hint": "Pass confirm=true to remove these extras."})
    wanted = _parse_names(names)
    if not wanted:
        return _dumps({"error": "no_names"})
    page = await _ensure_browser()
    ctx = await game_context(page, parent_slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    row = ctx["row"]
    parent_title = str(ctx["game"].get("name") or "")
    additions = [a for a in row.get("additions") or [] if isinstance(a, dict)]
    owned = [{"id": a.get("game_id"), "name": (a.get("game") or {}).get("name"), "category": (a.get("game") or {}).get("category")} for a in additions]
    drop: set[int] = set()
    report = []
    for name in wanted:
        hits = _match(name, owned, parent_title)
        if len(hits) != 1:
            report.append({"name": name, "status": "not_found" if not hits else "ambiguous"})
            continue
        drop.add(hits[0]["id"])
        report.append({"name": name, "status": "removed", "game_id": hits[0]["id"]})
    if not drop:
        return _dumps({"ok": True, "changed": False, "results": report})
    keep = [a for a in additions if a.get("game_id") not in drop]
    saved = await _save(page, row, {"additions": keep}, "remove_game_content")
    if saved.get("error"):
        return _dumps(saved)
    return _dumps({**saved, "results": report})


def register(mcp) -> None:
    mcp.tool()(locked_tool(list_collection_content_menus))
    mcp.tool()(locked_tool(add_game_content))
    mcp.tool()(locked_tool(remove_game_content))


__all__ = ["add_game_content", "api_error", "list_collection_content_menus", "remove_game_content"]
