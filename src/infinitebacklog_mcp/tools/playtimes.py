"""MCP tools: community playtime data (time to beat and time to complete) for games you have beaten or completed."""
from __future__ import annotations

from typing import Any

from ..api import api_error, current_user, ib_api, require_user_error
from ..browser import _ensure_browser, locked_tool
from ..normalize import _dumps, parse_minutes, slim_game
from ..pages import game_context

BEATEN_STATUSES = ("campaignCompleted", "completed")


def playtime_body(beaten_minutes: int, completed_minutes: int) -> dict[str, Any]:
    return {"campaign_completed": int(beaten_minutes), "completed": int(completed_minutes)}


def _target_game_id(game: dict[str, Any]) -> int:
    """Versions and editions report playtime against their parent game."""
    parent = game.get("version_parent")
    if parent and game.get("category") in (0, 3):
        parent_id = parent.get("id") if isinstance(parent, dict) else parent
        if parent_id:
            return int(parent_id)
    return int(game["id"])


async def list_playtime_contributions(limit: int = 25, offset: int = 0) -> str:
    """List the playtime figures you have submitted, newest first. Read-only."""
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    params: dict[str, Any] = {
        "user_id": me["id"],
        "limit": max(1, min(int(limit or 25), 100)),
        "offset": max(0, int(offset or 0)),
        "sort_field": "updated_at",
        "sort_order": "desc",
    }
    result = await ib_api(page, "GET", "/user_playtimes", params=params)
    if not result.get("ok"):
        return _dumps(api_error(result, "list_playtime_contributions"))
    rows = [r for r in result.get("data") or [] if isinstance(r, dict)]
    return _dumps(
        {
            "user": me["username"],
            "total": result.get("total"),
            "count": len(rows),
            "contributions": [{**r, "game": slim_game(r.get("game"))} for r in rows],
        },
        limit=40000,
    )


async def submit_playtime(
    slug: str,
    beaten_hours: str = "",
    beaten_minutes: str = "",
    completed_hours: str = "",
    completed_minutes: str = "",
    confirm: bool = False,
) -> str:
    """Submit your time to beat and time to complete a game to Infinite Backlog's public playtime data. Needs a copy marked Beaten or Completed and confirm=true. There is no delete: a submission can only be changed by submitting again."""
    if not confirm:
        return _dumps(
            {
                "error": "confirm_required",
                "hint": "This shares your times with Infinite Backlog's public playtime data and cannot be deleted. Pass confirm=true.",
            }
        )
    try:
        beaten = parse_minutes(beaten_hours, beaten_minutes) or 0
        completed = parse_minutes(completed_hours, completed_minutes) or 0
    except ValueError:
        return _dumps({"error": "invalid_time", "hint": "Hours and minutes must be numbers."})
    if beaten == 0 and completed == 0:
        return _dumps({"error": "nothing_to_submit", "hint": "Pass beaten_hours/beaten_minutes and/or completed_hours/completed_minutes."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False, full=True)
    if ctx.get("error"):
        return _dumps(ctx)
    if not any(str(r.get("completion")) in BEATEN_STATUSES for r in ctx["rows"]):
        return _dumps(
            {
                "error": "needs_beaten_or_completed",
                "hint": "Infinite Backlog only takes playtimes for a copy marked Beaten or Completed. Use set_game_progress first.",
            }
        )
    game = ctx["game"]
    existing = game.get("user_playtime") if isinstance(game.get("user_playtime"), dict) else {}
    body = playtime_body(beaten, completed)
    if existing.get("id"):
        result = await ib_api(page, "PUT", f"/user_playtimes/{int(existing['id'])}", body=body)
        status = "updated"
    else:
        result = await ib_api(page, "POST", "/user_playtimes", body={"game_id": _target_game_id(game), **body})
        status = "created"
    if not result.get("ok"):
        return _dumps(api_error(result, "submit_playtime"))
    return _dumps(
        {
            "ok": True,
            "status": status,
            "game": slim_game(game),
            "beaten_minutes": beaten,
            "completed_minutes": completed,
        }
    )


def register(mcp) -> None:
    mcp.tool()(locked_tool(list_playtime_contributions))
    mcp.tool()(locked_tool(submit_playtime))
