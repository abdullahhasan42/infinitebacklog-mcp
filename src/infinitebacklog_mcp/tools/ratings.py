"""MCP tools: per-game rating (overall 1-10 plus sub-ratings)."""
from __future__ import annotations

from typing import Any

from ..api import api_error, ib_api
from ..browser import _ensure_browser, locked_tool
from ..normalize import _dumps, parse_score, rating_label, slim_game
from ..pages import game_context

SUB_FIELDS = {
    "gameplay": "gameplay",
    "story": "story",
    "visual": "visual",
    "audio": "sound",
    "sound": "sound",
    "playability": "accessibility",
    "accessibility": "accessibility",
}


def _score(value: Any) -> int | None:
    parsed = parse_score(value)
    if parsed is None:
        return None
    n = int(round(parsed))
    if n < 1 or n > 10:
        raise ValueError("Scores are whole numbers from 1 to 10.")
    return n


async def set_game_rating(
    slug: str,
    score: str = "",
    gameplay: str = "",
    story: str = "",
    visual: str = "",
    audio: str = "",
    playability: str = "",
    clear: bool = False,
    collection_id: str = "",
    wait_ms: int = 0,
) -> str:
    """Rate a game 1-10 overall, with optional 1-10 sub-ratings for Gameplay, Story, Visual, Audio and Playability. Ratings are per game, not per copy. clear=true removes your rating. Sub-ratings you leave blank keep their current value."""
    del collection_id, wait_ms
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    me, gid = ctx["user"], ctx["game_id"]
    existing = await ib_api(page, "GET", "/ratings", params={"user_id": me["id"], "game_id": gid})
    current = existing.get("data") if existing.get("ok") and isinstance(existing.get("data"), dict) else None
    if clear:
        if not current or not current.get("id"):
            return _dumps({"ok": True, "status": "no_rating"})
        result = await ib_api(page, "DELETE", f"/ratings/{int(current['id'])}")
        if not result.get("ok"):
            return _dumps(api_error(result, "clear_rating"))
        return _dumps({"ok": True, "status": "cleared", "game": slim_game(ctx["game"])})
    try:
        values = {
            "score": _score(score),
            "gameplay": _score(gameplay),
            "story": _score(story),
            "visual": _score(visual),
            "sound": _score(audio),
            "accessibility": _score(playability),
        }
    except ValueError as exc:
        return _dumps({"error": "invalid_score", "hint": str(exc)})
    if all(v is None for v in values.values()):
        return _dumps({"error": "nothing_to_change", "current": current})
    body: dict[str, Any] = {"game_id": gid}
    for key in values:
        body[key] = (current or {}).get(key)
    body.update({k: v for k, v in values.items() if v is not None})
    if not body.get("score"):
        return _dumps({"error": "score_required", "hint": "An overall score is required for a new rating."})
    if current and current.get("id"):
        result = await ib_api(page, "PUT", f"/ratings/{int(current['id'])}", body=body)
    else:
        result = await ib_api(page, "POST", "/ratings", body=body)
    if not result.get("ok"):
        return _dumps(api_error(result, "set_game_rating"))
    saved = result.get("data") or {}
    return _dumps(
        {
            "ok": True,
            "game": slim_game(ctx["game"]),
            "rating": {k: saved.get(k) for k in ("id", "score", "gameplay", "story", "visual", "sound", "accessibility")},
            "label": rating_label(saved.get("score")),
        }
    )


def register(mcp) -> None:
    mcp.tool()(locked_tool(set_game_rating))
