"""MCP tools: write, publish, and delete your review of a game."""
from __future__ import annotations

from typing import Any

from ..api import api_error, ib_api
from ..browser import _ensure_browser, locked_tool
from ..config import REVIEW_MIN_PUBLISH_CHARS
from ..normalize import (
    _dumps,
    html_text_length,
    normalize_acquisition,
    normalize_completion,
    parse_score,
    slim_game,
    text_to_html,
)
from ..pages import game_context
from ..security import sanitize_username

_KEEP = (
    "title",
    "content",
    "pros",
    "cons",
    "language",
    "acquisition",
    "completion",
    "playtime",
    "score",
    "mature_content",
    "spoilers",
    "published",
    "visual",
    "story",
    "gameplay",
    "sound",
    "accessibility",
)


def _list(value: str) -> list[str]:
    import json

    raw = (value or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        parsed = json.loads(raw)
        return [str(x).strip() for x in parsed if str(x).strip()]
    return [line.strip(" -*\t") for line in raw.splitlines() if line.strip(" -*\t")]


async def _my_review(page, user: dict[str, Any], slug: str) -> dict[str, Any] | None:
    result = await ib_api(page, "GET", f"/users/{sanitize_username(user['username']).lower()}/reviews/{slug}")
    data = result.get("data")
    return data if result.get("ok") and isinstance(data, dict) and data.get("id") else None


async def add_game_review(
    slug: str,
    body: str,
    publish: bool = False,
    title: str = "",
    score: str = "",
    pros: str = "",
    cons: str = "",
    spoilers: bool = False,
    mature_content: bool = False,
    completion: str = "",
    acquisition: str = "",
    language: str = "",
    collection_id: str = "",
    wait_ms: int = 0,
) -> str:
    """Write or update your review. Saved as a draft unless publish=true. Publishing needs 800+ characters of text and an overall score (1-10). body is plain text (blank lines split paragraphs) or HTML. title 5-100 chars. pros/cons: JSON array or one per line. Re-running edits the same review."""
    del wait_ms
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    me, game = ctx["user"], ctx["game"]
    rows = ctx["rows"]
    row = rows[0] if rows else None
    if collection_id:
        row = next((r for r in rows if str(r.get("id")) == str(collection_id).strip()), row)
    existing = await _my_review(page, me, ctx["slug"])
    content = text_to_html(body)
    text_len = html_text_length(content)
    title = (title or "").strip()
    if title and not (5 <= len(title) <= 100):
        return _dumps({"error": "invalid_title", "hint": "Title must be 5 to 100 characters."})
    review_score = parse_score(score) if str(score).strip() else (existing or {}).get("score")
    if publish and text_len < REVIEW_MIN_PUBLISH_CHARS:
        return _dumps({"error": "too_short_to_publish", "chars": text_len, "min": REVIEW_MIN_PUBLISH_CHARS})
    if publish and not review_score:
        return _dumps({"error": "score_required_to_publish", "hint": "Pass score=1..10 to publish."})
    payload: dict[str, Any] = {k: (existing or {}).get(k) for k in _KEEP}
    payload.update(
        {
            "game_id": ctx["game_id"],
            "edition_id": (row or {}).get("edition_id"),
            "platform_id": (row or {}).get("platform_id") or ((game.get("platforms") or [None])[0]),
            "title": title or (existing or {}).get("title") or None,
            "content": content,
            "pros": _list(pros) if pros else (existing or {}).get("pros") or [],
            "cons": _list(cons) if cons else (existing or {}).get("cons") or [],
            "language": language or (existing or {}).get("language") or me.get("review_language") or "en",
            "acquisition": normalize_acquisition(acquisition) if acquisition else (existing or {}).get("acquisition") or (row or {}).get("acquisition") or "purchase",
            "completion": normalize_completion(completion) if completion else (existing or {}).get("completion") or (row or {}).get("completion") or "unfinished",
            "playtime": (existing or {}).get("playtime") or (row or {}).get("playtime") or 0,
            "score": int(review_score) if review_score else None,
            "spoilers": bool(spoilers),
            "mature_content": bool(mature_content),
            "post_feed": False,
            "published": bool(publish),
            "images": [],
        }
    )
    for key in ("visual", "story", "gameplay", "sound", "accessibility"):
        payload.setdefault(key, None)
    if payload["platform_id"] is not None:
        payload["platform_id"] = int(payload["platform_id"])
    if existing:
        result = await ib_api(page, "PUT", f"/reviews/{int(existing['id'])}", body=payload)
    else:
        result = await ib_api(page, "POST", "/reviews/", body=payload)
    if not result.get("ok"):
        return _dumps(api_error(result, "add_game_review"))
    saved = result.get("data") or {}
    return _dumps(
        {
            "ok": True,
            "game": slim_game(game),
            "review_id": saved.get("id"),
            "published": saved.get("published"),
            "status": "updated" if existing else "created",
            "chars": text_len,
            "url": f"https://infinitebacklog.net/users/{me['username'].lower()}/reviews/{ctx['slug']}",
        }
    )


async def delete_game_review(slug: str, confirm: bool = False, published: bool = False) -> str:
    """Delete your review of a game. Drafts need confirm=true. A published review also needs published=true, so it is never removed by accident."""
    if not confirm:
        return _dumps({"error": "confirm_required", "hint": "Pass confirm=true to delete the review."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    existing = await _my_review(page, ctx["user"], ctx["slug"])
    if not existing:
        return _dumps({"ok": True, "status": "no_review"})
    if existing.get("published") and not published:
        return _dumps(
            {
                "error": "profile_scope",
                "reason": "published_review",
                "hint": "This review is published. Pass published=true as well to delete it.",
            }
        )
    result = await ib_api(page, "DELETE", f"/reviews/{int(existing['id'])}")
    if not result.get("ok"):
        return _dumps(api_error(result, "delete_game_review"))
    return _dumps({"ok": True, "status": "deleted", "review_id": existing.get("id"), "was_published": bool(existing.get("published"))})


def register(mcp) -> None:
    mcp.tool()(locked_tool(add_game_review))
    mcp.tool()(locked_tool(delete_game_review))
