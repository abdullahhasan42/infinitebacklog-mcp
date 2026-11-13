"""MCP tools: catalog search, game details, related content, game stats, achievements."""
from __future__ import annotations

from typing import Any

from ..api import api_error, current_user, ib_api, related_games
from ..browser import _ensure_browser, locked_tool
from ..config import ADDON_CATEGORIES, DLC_CATEGORIES, EDITION_CATEGORIES
from ..normalize import _dumps, category_name, slim_game
from ..pages import clean_slug, resolve_game

# service id -> per-user achievement list endpoint (what the copy editor's Achievements tab calls)
ACHIEVEMENT_LIST_PATHS = {
    1: "/user_steam_games/{ext}/achievements",
    5: "/user_gog_games/{ext}/achievements",
    12: "/user_psn_games/{ext}/trophies",
    18: "/user_xbox_games/{ext}/achievements",
    102: "/user_retro_achievement_games/{ext}/achievements",
}

ACHIEVEMENT_SERVICES = {
    1: "steam",
    5: "gog",
    12: "playstation",
    18: "xbox",
    101: "ffxiv",
    102: "retroAchievements",
    103: "battle.net",
}


def _clamp(value: Any, low: int, high: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(low, min(n, high))


async def search_games(query: str, limit: int = 10, offset: int = 0) -> str:
    """Search the Infinite Backlog catalog. Returns name, slug, year and category per hit.

    Use the slug with the other tools. Duplicate titles get IGDB-style slugs
    (Hades 1995 is hades, Hades 2020 is hades--1).
    """
    q = (query or "").strip()
    if not q:
        return _dumps({"error": "query_required"})
    page = await _ensure_browser()
    result = await ib_api(
        page,
        "GET",
        "/games",
        params={"query": q, "limit": _clamp(limit, 1, 50, 10), "offset": _clamp(offset, 0, 5000, 0)},
    )
    if not result.get("ok"):
        return _dumps(api_error(result, "search_games"))
    hits = [slim_game(g) for g in result.get("data") or [] if isinstance(g, dict)]
    return _dumps({"query": q, "count": len(hits), "total": result.get("total"), "results": hits})


async def get_game(slug: str, full: bool = True) -> str:
    """Game details: summary, platforms, genres, developers, playtime averages, IB and critic scores, and your own collection/rating/wishlist state when signed in."""
    clean_slug(slug)
    page = await _ensure_browser()
    found = await resolve_game(page, slug, full=full)
    if found.get("error"):
        return _dumps(found)
    g = found["game"]
    out: dict[str, Any] = {
        **(slim_game(g) or {}),
        "summary": g.get("summary"),
        "storyline": g.get("storyline"),
        "platform_ids": g.get("platforms"),
        "genres": g.get("genres"),
        "developers": [d.get("name") for d in g.get("developers") or [] if isinstance(d, dict)],
        "publishers": [d.get("name") for d in g.get("publishers") or [] if isinstance(d, dict)],
        "ib_rating": g.get("rating_ib"),
        "ib_rating_count": g.get("rating_count_ib"),
        "critic_rating": g.get("aggregated_rating"),
        "playtime": g.get("playtime"),
        "version_parent": g.get("version_parent"),
        "parent_game": g.get("parent_game"),
    }
    for key in ("user_collection", "user_rating", "user_playtime", "user_wishlist"):
        if g.get(key) not in (None, {}, []):
            out[key] = g.get(key)
    return _dumps(out)


async def list_related_content(game_slug: str, wait_ms: int = 0) -> str:
    """List DLC, expansions, packs/add-ons, editions, bundles, remakes and other related games.

    Grouped the way the collection editor uses them: dlc (completion tracked), addons
    (packs, mods, updates), editions (bundles) and other. Public data; no login needed.
    """
    del wait_ms
    clean_slug(game_slug)
    page = await _ensure_browser()
    found = await resolve_game(page, game_slug)
    if found.get("error"):
        return _dumps(found)
    groups: dict[str, list[dict[str, Any]]] = {"dlc": [], "addons": [], "editions": [], "other": []}
    for item in await related_games(page, found["game_id"]):
        if item.get("id") == found["game_id"]:
            continue
        cat = item.get("category")
        entry = {**(slim_game(item) or {}), "kind": category_name(cat)}
        if cat in DLC_CATEGORIES:
            groups["dlc"].append(entry)
        elif cat in ADDON_CATEGORIES:
            groups["addons"].append(entry)
        elif cat in EDITION_CATEGORIES:
            groups["editions"].append(entry)
        else:
            groups["other"].append(entry)
    return _dumps(
        {
            "parent": slim_game(found["game"]),
            "counts": {k: len(v) for k, v in groups.items()},
            **groups,
        }
    )


async def get_game_stats(slug: str) -> str:
    """Community stats for a game: owners by status and completion, wishlist count, playtime averages, and rating distribution."""
    clean_slug(slug)
    page = await _ensure_browser()
    found = await resolve_game(page, slug, full=True)
    if found.get("error"):
        return _dumps(found)
    gid = found["game_id"]
    stats = await ib_api(page, "GET", "/user_collections/statistics", params={"game_id": gid})
    ratings = await ib_api(page, "GET", f"/games/{gid}/ratings")
    g = found["game"]
    return _dumps(
        {
            "game": slim_game(g),
            "collection": stats.get("data") if stats.get("ok") else api_error(stats, "statistics"),
            "ratings": ratings.get("data") if ratings.get("ok") else api_error(ratings, "ratings"),
            "ib_rating": g.get("rating_ib"),
            "ib_rating_count": g.get("rating_count_ib"),
            "critic_rating": g.get("aggregated_rating"),
            "playtime_minutes": g.get("playtime"),
        }
    )


async def list_achievements(slug: str = "", include_list: bool = False, limit: int = 30, max_per_set: int = 60) -> str:
    """Achievements and trophies.

    With slug: every achievement set for that game (Steam, PlayStation, Xbox, GOG,
    RetroAchievements) with your earned count when signed in. include_list=true also
    returns each achievement (name, description, unlocked state when synced).
    Without slug: your synced achievement games, newest first.
    Achievements come from linked store accounts. To track them by hand, use a
    checkbox Play Records category (set_play_record_category type=checkbox).
    """
    page = await _ensure_browser()
    me = await current_user(page)
    if not (slug or "").strip():
        if not me:
            return _dumps({"error": "not_logged_in", "hint": "Pass a slug, or sign in to list your achievement games."})
        result = await ib_api(
            page,
            "GET",
            "/user_accomplishment_games",
            params={
                "user_id": me["id"],
                "limit": _clamp(limit, 1, 100, 30),
                "offset": 0,
            },
        )
        if not result.get("ok"):
            return _dumps(api_error(result, "user_accomplishment_games"))
        status = await ib_api(page, "GET", "/user_accomplishment_games/status", params={"user_id": me["id"]})
        return _dumps(
            {
                "user": me["username"],
                "total": result.get("total"),
                "sync_status": status.get("data") if status.get("ok") else None,
                "games": result.get("data"),
            }
        )
    found = await resolve_game(page, slug)
    if found.get("error"):
        return _dumps(found)
    params: dict[str, Any] = {"game_id": found["game_id"]}
    if me:
        params["user_id"] = me["id"]
    result = await ib_api(page, "GET", "/accomplishment_games", params=params)
    if not result.get("ok"):
        return _dumps(api_error(result, "accomplishment_games"))
    sets = []
    for item in result.get("data") or []:
        if not isinstance(item, dict):
            continue
        entry = {
            "id": item.get("id"),
            "service": ACHIEVEMENT_SERVICES.get(item.get("service"), item.get("service")),
            "name": item.get("name"),
            "platform_ids": item.get("platforms"),
            "total": item.get("total_accomplishments"),
            "earned": item.get("earned_accomplishments"),
            "progress": item.get("progress"),
            "trophies": {k: item.get(k) for k in ("platinum", "gold", "silver", "bronze") if item.get(k) is not None},
        }
        path = ACHIEVEMENT_LIST_PATHS.get(item.get("service"))
        if include_list and path and item.get("external_id"):
            from urllib.parse import quote

            detail = await ib_api(
                page,
                "GET",
                path.format(ext=quote(str(item["external_id"]), safe="")),
                params={"user_id": me["id"]} if me else None,
            )
            data = detail.get("data") if detail.get("ok") else None
            rows = (data or {}).get("achievements") or (data or {}).get("trophies") if isinstance(data, dict) else None
            if rows is None and isinstance(data, dict):
                rows = [t for g in data.get("trophy_groups") or [] for t in g.get("trophies") or []]
            entry["achievements"] = (
                [
                    {
                        k: a.get(k)
                        for k in ("name", "description", "unlocked", "earned", "earned_date", "unlock_date", "rarity", "type", "grade")
                        if a.get(k) is not None
                    }
                    for a in (rows or [])[: _clamp(max_per_set, 1, 500, 60)]
                    if isinstance(a, dict)
                ]
                if detail.get("ok")
                else api_error(detail, "achievement_list")
            )
        sets.append(entry)
    return _dumps(
        {
            "game": slim_game(found["game"]),
            "signed_in": bool(me),
            "sets": sets,
            "hint": None
            if any(s["earned"] is not None for s in sets)
            else "No synced progress. Link Steam/PSN/Xbox/GOG/RetroAchievements in IB settings to sync it.",
        },
        limit=80000,
    )


def register(mcp) -> None:
    mcp.tool()(locked_tool(search_games))
    mcp.tool()(locked_tool(get_game))
    mcp.tool()(locked_tool(list_related_content))
    mcp.tool()(locked_tool(get_game_stats))
    mcp.tool()(locked_tool(list_achievements))
