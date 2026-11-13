"""MCP tools: the signed-in user's collection (copies, progress, details, acquisition)."""
from __future__ import annotations

import re
from typing import Any

from ..api import api_error, current_user, ib_api, platforms, require_user_error, save_rows
from ..browser import _ensure_browser, locked_tool
from ..config import STATUS_NAMES
from ..normalize import (
    _dumps,
    normalize_acquisition,
    normalize_completion,
    normalize_digital_store,
    normalize_ownership,
    normalize_status,
    parse_clear_fields,
    parse_minutes,
    parse_progress_pct,
    resolve_platform,
    slim_collection_row,
    slim_game,
)
from ..pages import game_context
from ..security import sanitize_collection_id

CONDITIONS = ("cib", "incomplete", "loose", "sealed")
PLAYTIME_TYPES = ("manual", "playthrough", "synced")
REGIONS = ("pal", "ntsc-u", "ntsc-j", "ntsc-c", "australia", "brazil", "asia", "korea", "other")
REGION_ALIASES = {
    "eu": "pal", "europe": "pal", "uk": "pal", "pal": "pal",
    "us": "ntsc-u", "usa": "ntsc-u", "na": "ntsc-u", "north america": "ntsc-u", "ntsc": "ntsc-u", "ntsc-u": "ntsc-u",
    "jp": "ntsc-j", "japan": "ntsc-j", "ntsc-j": "ntsc-j",
    "cn": "ntsc-c", "china": "ntsc-c", "ntsc-c": "ntsc-c",
    "au": "australia", "australia": "australia",
    "br": "brazil", "brazil": "brazil",
    "asia": "asia", "kr": "korea", "korea": "korea", "other": "other",
}
ZERO_DECIMAL_CURRENCIES = ("JPY", "VND", "KRW", "CLP")


def to_minor_units(amount: str, currency: str | None) -> int:
    """IB stores prices as integers in the currency's minor unit (cents), like its UI."""
    value = float(str(amount).replace(",", ".").strip())
    if (currency or "").upper() in ZERO_DECIMAL_CURRENCIES:
        return int(round(value))
    return int(round(value * 100))
PART_CONDITIONS = ("mint", "good", "acceptable", "poor", "missing", "na")
STATES = ("new", "used")
DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def _date_and_type(value: str) -> tuple[str, str]:
    """YYYY, YYYY-MM or YYYY-MM-DD -> (YYYY-MM-DD, year|month|day)."""
    m = DATE_RE.match((value or "").strip())
    if not m:
        raise ValueError("Use YYYY, YYYY-MM or YYYY-MM-DD.")
    year, month, day = m.group(1), m.group(2), m.group(3)
    if day:
        return f"{year}-{month}-{day}", "day"
    if month:
        return f"{year}-{month}-01", "month"
    return f"{year}-01-01", "year"


def new_row(game_id: int, platform_id: int, *, digital: bool, status: str = "unplayed") -> dict[str, Any]:
    """The object the SPA posts when a game is first added (captured from v2.1.0)."""
    return {
        "game_id": int(game_id),
        "status": status,
        "completion": "notStarted",
        "platform_id": int(platform_id),
        "ownership": "owned",
        "playtime_type": "manual",
        "subscription": None,
        "physical": not digital,
        "tags": [],
        "bundled_games": [],
        "edition_id": None,
        "edition": None,
        "additions": [],
    }


async def platform_names(page) -> dict[int, str]:
    return {int(p["id"]): str(p.get("name")) for p in await platforms(page) if p.get("id") is not None}


async def _save(page, row: dict[str, Any], changes: dict[str, Any], action: str) -> dict[str, Any]:
    updated = {**row, **changes}
    result = await save_rows(page, [updated])
    if not result.get("ok"):
        return api_error(result, action)
    data = result.get("data")
    saved = data[0] if isinstance(data, list) and data else updated
    return {"ok": True, "changed": sorted(changes), "copy": slim_collection_row(saved, await platform_names(page))}


async def _pick_platform(page, game: dict[str, Any], platform: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    all_platforms = await platforms(page)
    game_ids = {int(p) for p in game.get("platforms") or [] if str(p).isdigit()}
    on_game = [p for p in all_platforms if p.get("id") in game_ids]
    if not (platform or "").strip():
        if len(on_game) == 1:
            return on_game[0], None
        return None, {
            "error": "platform_required",
            "available": [p.get("name") for p in on_game],
        }
    hit = resolve_platform(platform, on_game) or resolve_platform(platform, all_platforms)
    if not hit:
        return None, {"error": "unknown_platform", "platform": platform, "available": [p.get("name") for p in on_game]}
    return hit, None


async def list_collection(
    status: str = "",
    search: str = "",
    limit: int = 25,
    offset: int = 0,
    sort: str = "updated_at",
    order: str = "desc",
) -> str:
    """List your collection. Filter by status (unplayed/playing/played/noStatus) or a title search."""
    page = await _ensure_browser()
    me = await current_user(page)
    if not me:
        return _dumps(require_user_error())
    params: dict[str, Any] = {
        "user_id": me["id"],
        "search": (search or "").strip(),
        "offset": max(0, int(offset or 0)),
        "limit": max(1, min(int(limit or 25), 100)),
        "sort_field": (sort or "updated_at").strip(),
        "sort_order": "asc" if str(order).lower() == "asc" else "desc",
    }
    if status:
        st = normalize_status(status)
        if not st:
            return _dumps({"error": "unknown_status", "allowed": list(STATUS_NAMES)})
        params["status"] = st
    result = await ib_api(page, "GET", "/user_collections", params=params)
    if not result.get("ok"):
        return _dumps(api_error(result, "list_collection"))
    rows = [r for r in result.get("data") or [] if isinstance(r, dict)]
    names = await platform_names(page)
    return _dumps(
        {
            "user": me["username"],
            "total": result.get("total"),
            "count": len(rows),
            "games": [{**(slim_game(r.get("game")) or {}), "copy": slim_collection_row(r, names)} for r in rows],
        },
        limit=40000,
    )


async def list_collection_game_options(slug: str, collection_id: str = "", wait_ms: int = 0) -> str:
    """Everything about your copies of one game: per-copy details, progress, acquisition, tags, DLC, play records id, playthroughs, your rating and your review. Read-only."""
    del wait_ms
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    me, gid = ctx["user"], ctx["game_id"]
    rows = ctx["rows"]
    if collection_id:
        cid = sanitize_collection_id(collection_id)
        rows = [r for r in rows if str(r.get("id")) == cid]
    rating = await ib_api(page, "GET", "/ratings", params={"user_id": me["id"], "game_id": gid})
    review = await ib_api(page, "GET", "/reviews", params={"user_id": me["id"], "game_id": gid, "limit": 1, "offset": 0})
    copies = []
    names = await platform_names(page)
    for row in rows:
        pts = await ib_api(page, "GET", f"/user_collections/{int(row['id'])}/playthroughs")
        copies.append(
            {
                **(slim_collection_row(row, names) or {}),
                "playthroughs": [
                    {k: p.get(k) for k in ("id", "name", "type", "playtime", "difficulty")}
                    | {"sessions": len(p.get("sessions") or [])}
                    for p in (pts.get("data") or [])
                    if isinstance(p, dict)
                ],
            }
        )
    reviews = review.get("data") if review.get("ok") else []
    first_review = reviews[0] if isinstance(reviews, list) and reviews else None
    return _dumps(
        {
            "game": slim_game(ctx["game"]),
            "copies": copies,
            "rating": rating.get("data") if rating.get("ok") and rating.get("data") else None,
            "review": {
                k: first_review.get(k) for k in ("id", "title", "published", "language", "completion", "spoilers", "updated_at")
            }
            if isinstance(first_review, dict)
            else None,
        }
    )


async def add_game_to_collection(
    slug: str,
    platform: str = "",
    digital: bool = False,
    status: str = "unplayed",
    allow_duplicate: bool = False,
) -> str:
    """Add a game to your collection (one copy on one platform). Refuses a second copy on the same platform unless allow_duplicate=true. For another platform use add_game_platform_copy."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    plat, err = await _pick_platform(page, ctx["game"], platform)
    if err:
        return _dumps(err)
    if not allow_duplicate and any(r.get("platform_id") == plat["id"] for r in ctx["rows"]):
        return _dumps(
            {
                "status": "already_in_collection",
                "copies": [slim_collection_row(r) for r in ctx["rows"]],
            }
        )
    st = normalize_status(status) or "unplayed"
    result = await save_rows(page, [new_row(ctx["game_id"], plat["id"], digital=digital, status=st)])
    if not result.get("ok"):
        return _dumps(api_error(result, "add_game_to_collection"))
    saved = (result.get("data") or [None])[0]
    return _dumps(
        {
            "ok": True,
            "game": slim_game(ctx["game"]),
            "platform": plat.get("name"),
            "copy": slim_collection_row(saved, await platform_names(page)),
        }
    )


async def add_game_platform_copy(slug: str, platform: str, digital: bool = False, submit: bool = True) -> str:
    """Add another copy of a game you already own, on another platform (its own progress, acquisition and play records)."""
    if not submit:
        return _dumps({"status": "not_submitted", "hint": "Pass submit=true to add the copy."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    if not ctx["rows"]:
        return _dumps({"error": "not_in_collection", "hint": "Use add_game_to_collection for the first copy."})
    plat, err = await _pick_platform(page, ctx["game"], platform)
    if err:
        return _dumps(err)
    result = await save_rows(page, [new_row(ctx["game_id"], plat["id"], digital=digital)])
    if not result.get("ok"):
        return _dumps(api_error(result, "add_game_platform_copy"))
    saved = (result.get("data") or [None])[0]
    return _dumps(
        {
            "ok": True,
            "platform": plat.get("name"),
            "copy": slim_collection_row(saved, await platform_names(page)),
            "copies_before": len(ctx["rows"]),
        }
    )


async def set_game_progress(
    slug: str,
    collection_id: str = "",
    status: str = "",
    completion: str = "",
    progress: str = "",
    notes: str = "",
    hours: str = "",
    minutes: str = "",
    times_completed: str = "",
    completion_date: str = "",
    clear_fields: str = "",
    playtime_type: str = "",
) -> str:
    """Set progress on one copy: status (unplayed/playing/played/noStatus), completion (notStarted/unfinished/beaten/completed/continuous/dropped), progress bar 0-100, notes, playtime (hours + minutes, saved as manual unless playtime_type says otherwise), finished playthroughs count, and completion date (YYYY, YYYY-MM or YYYY-MM-DD). playtime_type: manual, playthrough or synced. clear_fields empties: notes, progress, playtime, times_completed, completion_date."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    changes: dict[str, Any] = {}
    if status:
        st = normalize_status(status)
        if not st:
            return _dumps({"error": "unknown_status", "status": status})
        changes["status"] = st
    if completion:
        comp = normalize_completion(completion)
        if not comp:
            return _dumps({"error": "unknown_completion", "completion": completion})
        changes["completion"] = comp
    if str(progress).strip():
        changes["manual_progress"] = parse_progress_pct(progress)
    if notes:
        changes["notes"] = notes
    if playtime_type:
        pt_type = playtime_type.strip().lower()
        if pt_type not in PLAYTIME_TYPES:
            return _dumps({"error": "unknown_playtime_type", "playtime_type": playtime_type, "allowed": list(PLAYTIME_TYPES)})
        changes["playtime_type"] = pt_type
    total = parse_minutes(hours, minutes)
    if total is not None:
        changes["playtime"] = total
        changes.setdefault("playtime_type", "manual")
    if str(times_completed).strip():
        changes["times_completed"] = max(0, int(float(times_completed)))
    if completion_date:
        try:
            changes["completion_date"], changes["completion_date_type"] = _date_and_type(completion_date)
        except ValueError as exc:
            return _dumps({"error": "invalid_date", "hint": str(exc)})
    clears = {
        "notes": {"notes": ""},
        "progress": {"manual_progress": None},
        "playtime": {"playtime": 0},
        "times_completed": {"times_completed": None},
        "completion_date": {"completion_date": None, "completion_date_type": None},
    }
    for field in parse_clear_fields(clear_fields):
        if field not in clears:
            return _dumps({"error": "unknown_clear_field", "field": field, "allowed": sorted(clears)})
        changes.update(clears[field])
    if not changes:
        return _dumps({"error": "nothing_to_change"})
    return _dumps(await _save(page, ctx["row"], changes, "set_game_progress"))


async def set_game_details(
    slug: str,
    collection_id: str = "",
    platform: str = "",
    ownership: str = "",
    digital: str = "",
    region: str = "",
    edition_slug: str = "",
    lent_to: str = "",
    borrowed_from: str = "",
    clear_fields: str = "",
) -> str:
    """Basic info on one copy: platform, ownership (owned, household, subscription, borrowed, rented, unlicensed, formerlyOwned, lentOut, other), digital true/false, region (pal/EU, ntsc-u/US, ntsc-j/JP, ntsc-c, australia, brazil, asia, korea, other), edition (slug of an edition from list_related_content), lent_to, borrowed_from. clear_fields: edition, region, lent_to, borrowed_from."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    changes: dict[str, Any] = {}
    if platform:
        plat, err = await _pick_platform(page, ctx["game"], platform)
        if err:
            return _dumps(err)
        changes["platform_id"] = plat["id"]
    if ownership:
        own = normalize_ownership(ownership)
        if not own:
            return _dumps({"error": "unknown_ownership", "ownership": ownership})
        changes["ownership"] = own
    if str(digital).strip():
        changes["physical"] = str(digital).strip().lower() not in ("1", "true", "yes", "digital")
    if region:
        reg = REGION_ALIASES.get(region.strip().lower())
        if not reg:
            return _dumps({"error": "unknown_region", "region": region, "allowed": list(REGIONS)})
        changes["region"] = reg
    if edition_slug:
        from ..api import game_by_slug
        from ..pages import clean_slug

        edition = await game_by_slug(page, clean_slug(edition_slug))
        if not edition:
            return _dumps({"error": "edition_not_found", "edition_slug": edition_slug})
        changes["edition_id"] = edition["id"]
        changes["edition"] = {"id": edition["id"], "name": edition.get("name"), "slug": edition.get("slug")}
    if lent_to:
        changes["lent_to"] = lent_to
        changes["lent_out"] = True
    if borrowed_from:
        changes["borrowed_from"] = borrowed_from
    clears = {
        "edition": {"edition_id": None, "edition": None},
        "region": {"region": None},
        "lent_to": {"lent_to": "", "lent_out": None},
        "borrowed_from": {"borrowed_from": ""},
    }
    for field in parse_clear_fields(clear_fields):
        if field not in clears:
            return _dumps({"error": "unknown_clear_field", "field": field, "allowed": sorted(clears)})
        changes.update(clears[field])
    if not changes:
        return _dumps({"error": "nothing_to_change"})
    return _dumps(await _save(page, ctx["row"], changes, "set_game_details"))


async def set_game_acquisition(
    slug: str,
    collection_id: str = "",
    acquisition: str = "",
    source: str = "",
    date: str = "",
    amount: str = "",
    additional_costs: str = "",
    notes: str = "",
    digital_service: str = "",
    state: str = "",
    condition: str = "",
    condition_game: str = "",
    condition_box: str = "",
    condition_manual: str = "",
    clear_fields: str = "",
) -> str:
    """Acquisition and condition on one copy. acquisition: purchase, subscription, gift, trade, keyBundle, promotionalCopy, reviewCopy, free, freeToPlay. source: store or shop name (matched to IB's purchase places). date YYYY-MM-DD. amount and additional_costs are normal prices in your IB currency (9.99); the tool stores them the way IB does. digital_service: steam, epicGameStore, gog, psn, xboxLive, nintendoEShop, ... state new/used. condition cib/incomplete/loose/sealed. condition_game/box/manual: mint/good/acceptable/poor/missing/na. clear_fields empties any of those names."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    changes: dict[str, Any] = {}
    if acquisition:
        acq = normalize_acquisition(acquisition)
        if not acq:
            return _dumps({"error": "unknown_acquisition", "acquisition": acquisition})
        changes["acquisition"] = acq
    if source:
        places = await ib_api(page, "GET", "/purchase_places", params={"search": source, "limit": 20, "offset": 0})
        rows = places.get("data") if places.get("ok") else None
        rows = rows.get("data") if isinstance(rows, dict) else rows
        hit = None
        for p in rows or []:
            if isinstance(p, dict) and str(p.get("name") or "").casefold() == source.strip().casefold():
                hit = p
                break
        if hit:
            changes["purchase_place_id"] = hit.get("id")
            changes["purchase_place_name"] = hit.get("name")
        else:
            changes["purchase_place_id"] = None
            changes["purchase_place_name"] = source.strip()
    if date:
        try:
            changes["purchase_date"], _ = _date_and_type(date)
        except ValueError as exc:
            return _dumps({"error": "invalid_date", "hint": str(exc)})
    for key, value in (("purchase_price", amount), ("additional_cost", additional_costs)):
        if str(value).strip():
            try:
                changes[key] = to_minor_units(value, ctx["user"].get("currency"))
            except ValueError:
                return _dumps({"error": "invalid_amount", key: value})
    if notes:
        changes["acquisition_notes"] = notes
    if digital_service:
        store = normalize_digital_store(digital_service)
        if not store:
            return _dumps({"error": "unknown_digital_service", "digital_service": digital_service})
        changes["digital_store"] = store
    for key, value, allowed in (
        ("state", state, STATES),
        ("condition", condition, CONDITIONS),
        ("condition_game", condition_game, PART_CONDITIONS),
        ("condition_box", condition_box, PART_CONDITIONS),
        ("condition_manual", condition_manual, PART_CONDITIONS),
    ):
        if value:
            v = value.strip().lower()
            if v not in allowed:
                return _dumps({"error": f"unknown_{key}", key: value, "allowed": list(allowed)})
            changes[key] = v
    clears = {
        "acquisition": {"acquisition": None},
        "source": {"purchase_place_id": None, "purchase_place_name": None},
        "date": {"purchase_date": None},
        "amount": {"purchase_price": None},
        "additional_costs": {"additional_cost": None},
        "notes": {"acquisition_notes": ""},
        "digital_service": {"digital_store": None},
        "state": {"state": None},
        "condition": {"condition": None},
        "condition_game": {"condition_game": None},
        "condition_box": {"condition_box": None},
        "condition_manual": {"condition_manual": None},
    }
    for field in parse_clear_fields(clear_fields):
        if field not in clears:
            return _dumps({"error": "unknown_clear_field", "field": field, "allowed": sorted(clears)})
        changes.update(clears[field])
    if not changes:
        return _dumps({"error": "nothing_to_change"})
    return _dumps(await _save(page, ctx["row"], changes, "set_game_acquisition"))


async def delete_game_copy(slug: str, collection_id: str = "", confirm: bool = False) -> str:
    """Delete one copy from your collection, with its progress, acquisition and play records link. Needs collection_id and confirm=true."""
    if not confirm:
        return _dumps({"error": "confirm_required", "hint": "Pass confirm=true to delete this copy."})
    if not str(collection_id or "").strip():
        return _dumps({"error": "collection_id_required", "hint": "Pass the collection_id of the copy to delete."})
    page = await _ensure_browser()
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return _dumps(ctx)
    row = ctx["row"]
    result = await ib_api(page, "DELETE", f"/user_collections/{int(row['id'])}")
    if not result.get("ok"):
        return _dumps(api_error(result, "delete_game_copy"))
    return _dumps(
        {"ok": True, "deleted": slim_collection_row(row, await platform_names(page)), "copies_left": len(ctx["rows"]) - 1}
    )


def register(mcp) -> None:
    for fn in (
        list_collection,
        list_collection_game_options,
        add_game_to_collection,
        add_game_platform_copy,
        set_game_progress,
        set_game_details,
        set_game_acquisition,
        delete_game_copy,
    ):
        mcp.tool()(locked_tool(fn))
