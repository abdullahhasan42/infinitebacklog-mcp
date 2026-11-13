"""MCP tools: custom collection tags (an Infinite Backlog supporter feature)."""
from __future__ import annotations

import re
from typing import Any

from ..api import api_error, current_user, ib_api, require_user_error
from ..browser import _ensure_browser, locked_tool
from ..names import _parse_names
from ..normalize import _dumps, slim_collection_row
from ..pages import game_context
from .collection import _save

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _names(value: str) -> list[str]:
    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("[") or "\n" in raw:
        return _parse_names(raw)
    return [p.strip() for p in raw.split(",") if p.strip()]


async def _all_tags(page, user_id: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        result = await ib_api(
            page,
            "GET",
            "/user_collection_tags",
            params={"user_id": user_id, "limit": 100, "offset": offset, "sort_field": "name", "sort_order": "asc"},
        )
        batch = [t for t in result.get("data") or [] if isinstance(t, dict)] if result.get("ok") else []
        out.extend(batch)
        if len(batch) < 100:
            return out
        offset += 100


async def list_custom_tags() -> str:
    """List your custom collection tags (name, color, description)."""
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    tags = await _all_tags(page, me["id"])
    return _dumps(
        {
            "user": me["username"],
            "tags": [{k: t.get(k) for k in ("id", "name", "color", "description")} for t in tags],
            "note": None if tags else "No custom tags. Creating tags needs an IB supporter role; set_game_tags reports feature_locked if not.",
        }
    )


async def set_game_tags(
    slug: str,
    add: str = "",
    remove: str = "",
    collection_id: str = "",
    create_missing: bool = False,
    color: str = "#272727",
) -> str:
    """Add or remove custom tags on one copy. add/remove: comma-separated names or a JSON array. Tags that do not exist yet are created only with create_missing=true (supporter feature; otherwise feature_locked)."""
    to_add, to_remove = _names(add), _names(remove)
    if not to_add and not to_remove:
        return _dumps({"error": "nothing_to_change"})
    if color and not COLOR_RE.match(color):
        return _dumps({"error": "invalid_color", "hint": "Use #RRGGBB."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    library = {str(t.get("name")).casefold(): t for t in await _all_tags(page, ctx["user"]["id"])}
    row = ctx["row"]
    current = [t for t in row.get("tags") or [] if isinstance(t, dict)]
    have = {str(t.get("name")).casefold() for t in current}
    report: list[dict[str, Any]] = []
    for name in to_add:
        key = name.casefold()
        if key in have:
            report.append({"tag": name, "status": "already_set"})
            continue
        tag = library.get(key)
        if not tag:
            if not create_missing:
                report.append({"tag": name, "status": "missing", "hint": "Pass create_missing=true to create it."})
                continue
            made = await ib_api(page, "POST", "/user_collection_tags", body={"name": name, "description": "", "color": color})
            if not made.get("ok"):
                return _dumps({**api_error(made, "create_tag"), "tag": name})
            tag = made.get("data") or {}
            library[key] = tag
            report.append({"tag": name, "status": "created"})
        current.append({"id": tag.get("id"), "name": tag.get("name"), "color": tag.get("color"), "description": tag.get("description")})
        have.add(key)
        report.append({"tag": name, "status": "added"})
    drop = {n.casefold() for n in to_remove}
    if drop:
        before = len(current)
        current = [t for t in current if str(t.get("name")).casefold() not in drop]
        report.append({"removed": before - len(current)})
    if [t.get("id") for t in current] == [t.get("id") for t in row.get("tags") or [] if isinstance(t, dict)]:
        return _dumps({"ok": True, "changed": False, "results": report, "copy": slim_collection_row(row)})
    saved = await _save(page, row, {"tags": current}, "set_game_tags")
    return _dumps({**saved, "results": report})


async def delete_custom_tag(name: str, confirm: bool = False) -> str:
    """Delete a custom tag from your tag library (it disappears from every game). Needs confirm=true."""
    if not confirm:
        return _dumps({"error": "confirm_required", "hint": "This removes the tag from every game. Pass confirm=true."})
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    tag = next((t for t in await _all_tags(page, me["id"]) if str(t.get("name")).casefold() == name.strip().casefold()), None)
    if not tag:
        return _dumps({"error": "tag_not_found", "name": name})
    result = await ib_api(page, "DELETE", f"/user_collection_tags/{int(tag['id'])}")
    if not result.get("ok"):
        return _dumps(api_error(result, "delete_tag"))
    return _dumps({"ok": True, "status": "deleted", "tag": tag.get("name")})


def register(mcp) -> None:
    mcp.tool()(locked_tool(list_custom_tags))
    mcp.tool()(locked_tool(set_game_tags))
    mcp.tool()(locked_tool(delete_custom_tag))
