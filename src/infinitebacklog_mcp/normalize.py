"""Value parsers, aliases, and collection-row shaping."""
from __future__ import annotations

import json
import re
from typing import Any

from .config import (
    ACQUISITION_ALIASES,
    ACQUISITION_NAMES,
    COMPLETION_ALIASES,
    COMPLETION_NAMES,
    DIGITAL_STORE_NAMES,
    GAME_CATEGORIES,
    OWNERSHIP_ALIASES,
    OWNERSHIP_NAMES,
    PLAY_RECORD_TYPE_ALIASES,
    PLAY_RECORD_TYPES,
    PLAYTHROUGH_TYPE_ALIASES,
    PLAYTHROUGH_TYPES,
    RATING_SCORE_LABELS,
    SESSION_STATUS_ALIASES,
    SESSION_STATUSES,
    STATUS_ALIASES,
    STATUS_NAMES,
)

def _dumps(obj: Any, limit: int = 15000) -> str:
    """JSON for a tool reply. Always valid JSON: oversized replies are compacted, then
    wrapped as a truncated preview instead of being cut mid-structure."""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    compact = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(compact) <= limit:
        return compact
    hint = "The reply was too large. Narrow the request (smaller limit, max_per_set, or a single item)."
    size = max(0, limit - 300)
    while True:
        out = json.dumps({"truncated": True, "hint": hint, "preview": compact[:size]}, ensure_ascii=False)
        if len(out) <= limit or size == 0:
            return out
        size = max(0, size - (len(out) - limit) - 50)


def _alias_key(value: str) -> str:
    return re.sub(r"[_\-]+", " ", (value or "").strip().lower())


def rating_label(score: float | int | None) -> str | None:
    if score is None:
        return None
    try:
        n = int(round(float(score)))
    except (TypeError, ValueError):
        return None
    return RATING_SCORE_LABELS.get(n)


def normalize_status(value: str) -> str | None:
    if not (value or "").strip():
        return None
    raw = value.strip()
    if raw in STATUS_NAMES:
        return raw
    key = _alias_key(raw)
    return STATUS_ALIASES.get(key) or STATUS_ALIASES.get(key.replace(" ", ""))


def normalize_completion(value: str) -> str | None:
    if not (value or "").strip():
        return None
    raw = value.strip()
    if raw in COMPLETION_NAMES:
        return raw
    key = _alias_key(raw)
    compact = key.replace(" ", "")
    return COMPLETION_ALIASES.get(key) or COMPLETION_ALIASES.get(compact)


def parse_score(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def parse_progress_pct(value: str | float | int | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    pct = int(round(float(text)))
    return max(0, min(100, pct))


def parse_clear_fields(value: str | list | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    return [p.strip() for p in re.split(r"[,|]", text) if p.strip()]


def normalize_acquisition(value: str) -> str | None:
    if not (value or "").strip():
        return None
    raw = value.strip()
    if raw in ACQUISITION_NAMES:
        return raw
    key = _alias_key(raw)
    compact = key.replace(" ", "")
    return ACQUISITION_ALIASES.get(key) or ACQUISITION_ALIASES.get(compact)


def normalize_digital_store(value: str) -> str | None:
    if not (value or "").strip():
        return None
    raw = value.strip()
    if raw in DIGITAL_STORE_NAMES:
        return raw
    key = _alias_key(raw)
    for api_id, name in DIGITAL_STORE_NAMES.items():
        if key == _alias_key(name) or key == _alias_key(api_id):
            return api_id
        if key in _alias_key(name) or _alias_key(name) in key:
            return api_id
    return None


def normalize_play_record_type(value: str) -> str | None:
    if not (value or "").strip():
        return None
    raw = value.strip()
    if raw in PLAY_RECORD_TYPES:
        return raw
    key = _alias_key(raw)
    compact = key.replace(" ", "")
    return PLAY_RECORD_TYPE_ALIASES.get(key) or PLAY_RECORD_TYPE_ALIASES.get(compact)


def profile_scope(reason: str, detail: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "error": "profile_scope",
        "reason": reason,
        "hint": "This would write the existing profile or a global category/tag library. Name the change in chat first.",
    }
    if detail is not None:
        out["detail"] = detail
    return out


def slim_collection_row(
    row: dict[str, Any] | None, platform_names: dict[int, str] | None = None
) -> dict[str, Any] | None:
    if not row:
        return None
    rating = row.get("rating") if isinstance(row.get("rating"), dict) else None
    platform = None
    plat_obj = row.get("platform")
    if isinstance(plat_obj, dict):
        platform = plat_obj.get("name") or plat_obj.get("abbreviation")
    if platform is None and platform_names:
        platform = platform_names.get(row.get("platform_id"))
    acq = row.get("acquisition")
    store = row.get("digital_store")
    return {
        "id": row.get("id"),
        "game_id": row.get("game_id"),
        "platform_id": row.get("platform_id"),
        "platform": platform,
        "status": row.get("status"),
        "status_name": STATUS_NAMES.get(str(row.get("status") or ""), row.get("status")),
        "completion": row.get("completion"),
        "completion_name": COMPLETION_NAMES.get(str(row.get("completion") or ""), row.get("completion")),
        "ownership": row.get("ownership"),
        "physical": row.get("physical"),
        "format": "Physical" if row.get("physical") else "Digital",
        "notes": row.get("notes") or "",
        "manual_progress": row.get("manual_progress"),
        "progress": row.get("progress"),
        "edition_id": row.get("edition_id"),
        "rating": rating,
        "acquisition": acq,
        "acquisition_name": ACQUISITION_NAMES.get(str(acq or ""), acq),
        "ownership_name": OWNERSHIP_NAMES.get(str(row.get("ownership") or ""), row.get("ownership")),
        "digital_store": store,
        "digital_store_name": DIGITAL_STORE_NAMES.get(str(store or ""), store),
        "subscription": row.get("subscription"),
        "purchase_place_id": row.get("purchase_place_id"),
        "purchase_place_name": row.get("purchase_place_name"),
        "purchase_date": row.get("purchase_date"),
        "purchase_price_minor": row.get("purchase_price"),
        "additional_cost_minor": row.get("additional_cost"),
        "acquisition_notes": row.get("acquisition_notes"),
        "gameplay_stats_id": row.get("gameplay_stats_id"),
        "borrowed_from": row.get("borrowed_from"),
        "lent_to": row.get("lent_to"),
        "condition": row.get("condition"),
        "region": row.get("region"),
        "playtime_minutes": row.get("playtime"),
        "playtime_type": row.get("playtime_type"),
        "times_completed": row.get("times_completed"),
        "completion_date": row.get("completion_date"),
        "lent_out": row.get("lent_out"),
        "state": row.get("state"),
        "condition_game": row.get("condition_game"),
        "condition_box": row.get("condition_box"),
        "condition_manual": row.get("condition_manual"),
        "playthrough_id": row.get("playthrough_id"),
        "tags": [
            {"id": t.get("id"), "name": t.get("name")}
            for t in row.get("tags") or []
            if isinstance(t, dict)
        ],
        "additions": [
            {
                "game_id": a.get("game_id"),
                "name": (a.get("game") or {}).get("name"),
                "category": category_name((a.get("game") or {}).get("category")),
                "completion": a.get("completion"),
            }
            for a in row.get("additions") or []
            if isinstance(a, dict)
        ],
        "achievements": {
            "earned": row.get("earned_accomplishments"),
            "total": row.get("total_accomplishments"),
        },
    }


def _lookup(value: str, exact: tuple | dict, aliases: dict[str, str]) -> str | None:
    if not (value or "").strip():
        return None
    raw = value.strip()
    if raw in exact:
        return raw
    key = _alias_key(raw)
    return aliases.get(key) or aliases.get(key.replace(" ", ""))


def normalize_ownership(value: str) -> str | None:
    return _lookup(value, OWNERSHIP_NAMES, OWNERSHIP_ALIASES)


def normalize_playthrough_type(value: str) -> str | None:
    return _lookup(value, PLAYTHROUGH_TYPES, PLAYTHROUGH_TYPE_ALIASES)


def normalize_session_status(value: str) -> str | None:
    return _lookup(value, SESSION_STATUSES, SESSION_STATUS_ALIASES)


_PLATFORM_ALIASES = {
    "windows": "windows pc",
    "win": "windows pc",
    "microsoft windows": "windows pc",
    "pc (microsoft windows)": "windows pc",
    "steam deck": "windows pc",
    "switch": "nintendo switch",
    "switch 2": "nintendo switch 2",
    "xbox series": "xbox series x|s",
    "xbox series x": "xbox series x|s",
    "xbox series s": "xbox series x|s",
    "xsx": "xbox series x|s",
    "xbox one": "xbox one",
    "xone": "xbox one",
    "macos": "mac",
}


def resolve_platform(value: str, platforms: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match a platform id, name, abbreviation, alternative name or slug from /api/startup."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return next((p for p in platforms if str(p.get("id")) == raw), None)
    fields = ("name", "abbreviation", "alternative_name", "slug")
    for key in dict.fromkeys((raw.casefold(), _PLATFORM_ALIASES.get(raw.casefold(), ""))):
        if not key:
            continue
        for field in fields:
            for p in platforms:
                if str(p.get(field) or "").casefold() == key:
                    return p
    hits = [p for p in platforms if raw.casefold() in str(p.get("name") or "").casefold()]
    return hits[0] if len(hits) == 1 else None


_UNSAFE_HTML = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|style|link|meta|form|input|svg)\b|javascript:|data:text/html|\son\w+\s*=",
    re.I,
)


def is_safe_html(content: str) -> bool:
    """Plain formatting HTML only: no scripts, frames, forms, styles or event handlers."""
    return not _UNSAFE_HTML.search(content or "")


def text_to_html(text: str) -> str:
    """Plain text to the <p> paragraphs IB's editor stores. Simple safe HTML passes through; anything else is escaped."""
    body = (text or "").strip()
    if not body:
        return "<p></p>"
    if re.match(r"^\s*<(p|h\d|ul|ol|blockquote|div)[\s>]", body, re.I) and is_safe_html(body):
        return body
    import html

    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in parts)


def html_text_length(content: str) -> int:
    return len(re.sub(r"<[^>]*>?", "", content or "").strip())


def parse_minutes(hours: Any = None, minutes: Any = None) -> int | None:
    """hours/minutes text to total minutes. None when both are blank."""
    h = str(hours if hours is not None else "").strip()
    m = str(minutes if minutes is not None else "").strip()
    if not h and not m:
        return None
    total = float(h or 0) * 60 + float(m or 0)
    return max(0, int(round(total)))


def category_name(category: Any) -> str:
    try:
        return GAME_CATEGORIES.get(int(category), str(category))
    except (TypeError, ValueError):
        return str(category)


def slim_game(game: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(game, dict):
        return None
    year = None
    ts = game.get("first_release_date")
    if isinstance(ts, (int, float)) and ts > 0:
        import datetime as _dt

        year = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).year
    return {
        "id": game.get("id"),
        "name": game.get("name"),
        "slug": game.get("slug"),
        "year": year,
        "category": category_name(game.get("category")),
        "url": f"https://infinitebacklog.net/games/{game.get('slug')}" if game.get("slug") else None,
    }
