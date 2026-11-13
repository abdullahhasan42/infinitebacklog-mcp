"""MCP tools: playthroughs and play sessions (the v2 play log) for one copy."""
from __future__ import annotations

import re
from typing import Any

from ..api import api_error, current_user, ib_api, require_user_error
from ..browser import _ensure_browser, locked_tool
from ..config import PLAYTHROUGH_PLAYTIME_TYPES, PLAYTHROUGH_TYPES, SESSION_STATUSES
from ..normalize import _dumps, normalize_playthrough_type, normalize_session_status, parse_minutes, slim_game
from ..pages import game_context

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _slim_session(s: dict[str, Any]) -> dict[str, Any]:
    return {k: s.get(k) for k in ("id", "date", "duration", "status", "content", "platform_id") if s.get(k) not in (None, "")}


def _slim_playthrough(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "type": p.get("type"),
        "difficulty": p.get("difficulty"),
        "notes": p.get("notes"),
        "playtime_type": p.get("playtime_type"),
        "playtime_minutes": p.get("playtime"),
        "duration_minutes": p.get("duration"),
        "copies": p.get("collection_games"),
        "sessions": [_slim_session(s) for s in p.get("sessions") or [] if isinstance(s, dict)],
    }


async def _playthroughs(page, cid: int) -> list[dict[str, Any]]:
    result = await ib_api(page, "GET", f"/user_collections/{cid}/playthroughs")
    data = result.get("data")
    return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []


def _find(pts: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    key = (key or "").strip()
    if not key:
        saved = [p for p in pts if p.get("id")]
        return saved[0] if len(saved) == 1 else None
    for p in pts:
        if str(p.get("id")) == key:
            return p
    hits = [p for p in pts if str(p.get("name") or "").casefold() == key.casefold()]
    return hits[0] if len(hits) == 1 else None


async def list_playthroughs(slug: str, collection_id: str = "") -> str:
    """List playthroughs of one copy with their sessions (date, minutes, status, notes). A copy always shows a default "Playthrough" until you save one."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    pts = await _playthroughs(page, int(ctx["row"]["id"]))
    return _dumps(
        {
            "game": slim_game(ctx["game"]),
            "collection_id": ctx["row"]["id"],
            "playthroughs": [_slim_playthrough(p) for p in pts],
            "types": list(PLAYTHROUGH_TYPES),
        }
    )


async def set_playthrough(
    slug: str,
    collection_id: str = "",
    playthrough: str = "",
    name: str = "",
    type: str = "",
    difficulty: str = "",
    notes: str = "",
    playtime_type: str = "",
    hours: str = "",
    minutes: str = "",
    create: bool = False,
    extra_hours: str = "",
    extra_minutes: str = "",
) -> str:
    """Create or edit a playthrough on one copy. create=true adds a new one; otherwise playthrough (id or name) picks the one to edit, and an unsaved default playthrough is saved first. type: firstPlaythrough, replay, speedrun, coop, competitive, continuous, streaming, achievements, challengeRun. playtime_type: session (sum of sessions) or playthrough (set hours/minutes directly). hours/minutes set the manual duration. extra_hours/extra_minutes set playtime_offset: minutes added on top of the session total."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    cid = int(ctx["row"]["id"])
    fields: dict[str, Any] = {}
    if name:
        fields["name"] = name.strip()
    if type:
        t = normalize_playthrough_type(type)
        if not t:
            return _dumps({"error": "unknown_type", "type": type, "allowed": list(PLAYTHROUGH_TYPES)})
        fields["type"] = t
    if difficulty:
        fields["difficulty"] = difficulty.strip()
    if notes:
        fields["notes"] = notes
    if playtime_type:
        pt_type = playtime_type.strip().lower()
        if pt_type not in PLAYTHROUGH_PLAYTIME_TYPES:
            return _dumps({"error": "unknown_playtime_type", "allowed": list(PLAYTHROUGH_PLAYTIME_TYPES)})
        fields["playtime_type"] = pt_type
    total = parse_minutes(hours, minutes)
    if total is not None:
        fields["duration"] = total
        fields.setdefault("playtime_type", "playthrough")
    offset = parse_minutes(extra_hours, extra_minutes)
    if offset is not None:
        fields["playtime_offset"] = offset
    if create:
        body = {
            "bundle": None,
            "collection_games": [cid],
            "difficulty": None,
            "duration": 0,
            "name": "Playthrough",
            "notes": "",
            "playtime_type": "session",
            "sessions": [],
            "type": "firstPlaythrough",
            **fields,
        }
        result = await ib_api(page, "POST", f"/user_collections/{cid}/playthroughs", body=body)
        if not result.get("ok"):
            return _dumps(api_error(result, "add_playthrough"))
        return _dumps({"ok": True, "status": "created", "playthrough": _slim_playthrough(result.get("data") or {})})
    pts = await _playthroughs(page, cid)
    if not any(p.get("id") for p in pts):
        init = await ib_api(page, "POST", f"/user_collections/{cid}/playthroughs/init")
        if not init.get("ok"):
            return _dumps(api_error(init, "init_playthrough"))
        pts = await _playthroughs(page, cid)
    target = _find(pts, playthrough)
    if not target:
        return _dumps({"error": "playthrough_required", "hint": "Pass playthrough (id or name).", "playthroughs": [_slim_playthrough(p) for p in pts]})
    if not fields:
        return _dumps({"ok": True, "status": "unchanged", "playthrough": _slim_playthrough(target)})
    body = {**target, **fields}
    body.pop("sessions", None)
    result = await ib_api(page, "PUT", f"/user_collection_playthroughs/{int(target['id'])}?user_collection_id={cid}", body=body)
    if not result.get("ok"):
        return _dumps(api_error(result, "edit_playthrough"))
    return _dumps({"ok": True, "status": "updated", "changed": sorted(fields), "playthrough": _slim_playthrough(result.get("data") or body)})


async def remove_playthrough(slug: str, playthrough: str, collection_id: str = "", confirm: bool = False) -> str:
    """Delete a playthrough and all its sessions. Needs confirm=true."""
    if not confirm:
        return _dumps({"error": "confirm_required", "hint": "Pass confirm=true to delete the playthrough and its sessions."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    pts = await _playthroughs(page, int(ctx["row"]["id"]))
    target = _find([p for p in pts if p.get("id")], playthrough)
    if not target:
        return _dumps({"error": "playthrough_not_found", "playthrough": playthrough})
    result = await ib_api(page, "DELETE", f"/user_collection_playthroughs/{int(target['id'])}")
    if not result.get("ok"):
        return _dumps(api_error(result, "delete_playthrough"))
    return _dumps({"ok": True, "status": "deleted", "playthrough": _slim_playthrough(target)})


async def add_play_session(
    slug: str,
    date: str,
    minutes: str = "",
    hours: str = "",
    status: str = "playing",
    notes: str = "",
    playthrough: str = "",
    collection_id: str = "",
    session_id: str = "",
) -> str:
    """Log a play session (date YYYY-MM-DD, hours/minutes played, status, notes) on a playthrough of one copy. Pass session_id to edit an existing session instead. status: start, playing, campaignCompleted (beaten), completed, shelved, dropped. Sessions are capped at 24h each."""
    if not DATE_RE.match((date or "").strip()):
        return _dumps({"error": "invalid_date", "hint": "Use YYYY-MM-DD."})
    st = normalize_session_status(status or "playing")
    if not st:
        return _dumps({"error": "unknown_status", "allowed": list(SESSION_STATUSES)})
    duration = parse_minutes(hours, minutes) or 0
    if duration > 1440:
        return _dumps({"error": "too_long", "hint": "A session is at most 24 hours (1440 minutes)."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    cid = int(ctx["row"]["id"])
    pts = await _playthroughs(page, cid)
    if not any(p.get("id") for p in pts):
        init = await ib_api(page, "POST", f"/user_collections/{cid}/playthroughs/init")
        if not init.get("ok"):
            return _dumps(api_error(init, "init_playthrough"))
        pts = await _playthroughs(page, cid)
    target = _find([p for p in pts if p.get("id")], playthrough)
    if not target:
        return _dumps({"error": "playthrough_required", "playthroughs": [_slim_playthrough(p) for p in pts]})
    pid = int(target["id"])
    body = {
        "content": notes or "",
        "date": date.strip(),
        "dlc": None,
        "duration": duration,
        "friends": [],
        "platform_id": ctx["row"].get("platform_id"),
        "season": None,
        "status": st,
        "stream": None,
        "update": None,
        "post_feed": False,
        "post_spoilers": False,
        "post_mature_content": False,
        "user_collection_playthrough_id": pid,
    }
    if session_id:
        existing = next((s for s in target.get("sessions") or [] if str(s.get("id")) == str(session_id).strip()), None)
        if not existing:
            return _dumps({"error": "session_not_found", "session_id": session_id})
        merged = {**existing, **{k: v for k, v in body.items() if k not in ("post_feed", "post_spoilers", "post_mature_content")}}
        if not notes:
            merged["content"] = existing.get("content")
        if not (hours or minutes):
            merged["duration"] = existing.get("duration")
        result = await ib_api(
            page, "PUT", f"/user_collection_playthroughs/{pid}/sessions/{int(existing['id'])}?user_collection_id={cid}", body=merged
        )
        action = "updated"
    else:
        result = await ib_api(page, "POST", f"/user_collection_playthroughs/{pid}/sessions", body=body)
        action = "created"
    if not result.get("ok"):
        return _dumps(api_error(result, "play_session"))
    return _dumps({"ok": True, "status": action, "playthrough": target.get("name"), "session": _slim_session(result.get("data") or {})})


async def remove_play_session(slug: str, session_id: str, collection_id: str = "", confirm: bool = False) -> str:
    """Delete one play session by id. Needs confirm=true."""
    if not confirm:
        return _dumps({"error": "confirm_required"})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    for p in await _playthroughs(page, int(ctx["row"]["id"])):
        for s in p.get("sessions") or []:
            if str(s.get("id")) == str(session_id).strip():
                result = await ib_api(page, "DELETE", f"/user_collection_playthroughs/{int(p['id'])}/sessions/{int(s['id'])}")
                if not result.get("ok"):
                    return _dumps(api_error(result, "delete_session"))
                return _dumps({"ok": True, "status": "deleted", "session": _slim_session(s)})
    return _dumps({"error": "session_not_found", "session_id": session_id})


async def get_play_journal(limit: int = 20, offset: int = 0) -> str:
    """Your recent play sessions across all games (the IB journal), newest first."""
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    result = await ib_api(
        page,
        "GET",
        "/user_collection_playthrough_sessions",
        params={
            "user_id": me["id"],
            "limit": max(1, min(int(limit or 20), 100)),
            "offset": max(0, int(offset or 0)),
            "sort_field": "date",
            "sort_order": "desc",
        },
    )
    if not result.get("ok"):
        return _dumps(api_error(result, "journal"))
    return _dumps({"user": me["username"], "total": result.get("total"), "sessions": result.get("data")})


def register(mcp) -> None:
    for fn in (list_playthroughs, set_playthrough, remove_playthrough, add_play_session, remove_play_session, get_play_journal):
        mcp.tool()(locked_tool(fn))
