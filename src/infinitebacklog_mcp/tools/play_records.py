"""MCP tools: Play Records (per-copy categories of key/values, checklists, progress bars, tables and notes)."""
from __future__ import annotations

import json
import re
from typing import Any

from ..api import api_error, ib_api
from ..browser import _ensure_browser, locked_tool
from ..config import PLAY_RECORD_TYPES
from ..normalize import _dumps, normalize_play_record_type, slim_collection_row, slim_game, text_to_html
from ..pages import game_context

_TRUE = ("1", "true", "yes", "y", "done", "unlocked", "x", "checked")


def _empty_category(name: str, type_id: str, columns: int, order: int, parent_id: Any = None) -> dict[str, Any]:
    """The SPA's new-category object (v2.1.0)."""
    return {
        "name": name,
        "bordered": False,
        "columns": columns,
        "type": type_id,
        "description_available": False,
        "date_available": False,
        "data": [],
        "order": order,
        "icon": None,
        "parent_id": parent_id,
        "icon_size": "small",
        "dlc_game_id": None,
        "bundled_game_id": None,
    }


def _walk(categories: list[dict[str, Any]]):
    for cat in categories or []:
        yield cat
        yield from _walk(cat.get("children") or [])


def _find_category(stats: dict[str, Any], category: str) -> dict[str, Any] | None:
    key = (category or "").strip()
    cats = list(_walk(stats.get("categories") or []))
    if key.isdigit():
        for cat in cats:
            if str(cat.get("id")) == key:
                return cat
    for cat in cats:
        if str(cat.get("name") or "").casefold() == key.casefold():
            return cat
    return None


def _summarize(cat: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for idx, item in enumerate(cat.get("data") or [], start=1):
        if not isinstance(item, dict):
            continue
        clean = {k: v for k, v in item.items() if k not in ("icon", "order") and v not in (None, "")}
        rows.append({"row": idx, **clean})
    out = {
        "id": cat.get("id"),
        "name": cat.get("name"),
        "type": cat.get("type"),
        "columns": cat.get("columns"),
        "rows": rows,
    }
    if cat.get("achievements"):
        out["achievements"] = True
    if cat.get("children"):
        out["children"] = [_summarize(c) for c in cat["children"]]
    return out


async def _load(page, slug: str, collection_id: str, *, create: bool = False) -> dict[str, Any]:
    ctx = await game_context(page, slug, collection_id)
    if ctx.get("error"):
        return ctx
    row = ctx["row"]
    stats_id = row.get("gameplay_stats_id")
    if not stats_id:
        if not create:
            return {**ctx, "stats": None}
        made = await ib_api(page, "POST", f"/user_collections/{int(row['id'])}/gameplay_stats")
        if not made.get("ok"):
            return api_error(made, "create_play_records")
        stats_id = (made.get("data") or {}).get("id")
    got = await ib_api(page, "GET", f"/user_collection_gameplay_stats/{int(stats_id)}")
    if not got.get("ok"):
        return api_error(got, "get_play_records")
    return {**ctx, "stats": got.get("data")}


def _parse_values(value: str) -> list[str]:
    raw = (value or "").strip()
    if raw.startswith("["):
        return [str(x) for x in json.loads(raw)]
    return [p.strip() for p in raw.split("|")]


def _row_for(cat_type: str, base: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    """Merge caller fields into one row of the given category type."""
    row = dict(base)
    name, value = fields.get("name"), fields.get("value")
    if cat_type == "keyValue":
        row.setdefault("icon", "")
        if name is not None:
            row["name"] = name
        if value is not None:
            row["value"] = value
    elif cat_type == "checkbox":
        row.setdefault("icon", "")
        row.setdefault("unlocked", False)
        row.setdefault("earned_date", None)
        if name is not None:
            row["name"] = name
        unlocked = fields.get("unlocked")
        if unlocked is None and value is not None:
            unlocked = str(value).strip().lower() in _TRUE
        if unlocked is not None:
            row["unlocked"] = bool(unlocked)
    elif cat_type == "progress":
        row.setdefault("icon", "")
        row.setdefault("description", "")
        row.setdefault("progress_earned", 0)
        row.setdefault("progress_total", 0)
        row.setdefault("earned_date", None)
        if name is not None:
            row["name"] = name
        if value is not None and str(value).strip():
            m = re.match(r"^\s*([\d.]+)\s*(?:/\s*([\d.]+))?\s*$", str(value))
            if m:
                row["progress_earned"] = float(m.group(1))
                if m.group(2):
                    row["progress_total"] = float(m.group(2))
        for key in ("progress_earned", "progress_total"):
            if fields.get(key) is not None:
                row[key] = float(fields[key])
    elif cat_type == "table":
        if fields.get("values") is not None:
            row["values"] = fields["values"]
        elif value is not None:
            row["values"] = _parse_values(str(value))
        row.setdefault("values", [""])
    elif cat_type == "text":
        content = fields.get("content", value)
        if content is not None:
            row["content"] = text_to_html(str(content))
        row.setdefault("content", "")
    if fields.get("description") is not None and cat_type in ("progress", "checkbox", "keyValue"):
        row["description"] = fields["description"]
    if fields.get("earned_date") is not None:
        row["earned_date"] = fields["earned_date"] or None
    return row


async def list_play_records(slug: str, collection_id: str = "", wait_ms: int = 0) -> str:
    """Read the Play Records of one copy: every category (key/value, checklist, progress, table, text) and its rows, numbered from 1. Read-only."""
    del wait_ms
    page = await _ensure_browser()
    loaded = await _load(page, slug, collection_id)
    if loaded.get("error"):
        return _dumps(loaded)
    stats = loaded.get("stats")
    return _dumps(
        {
            "game": slim_game(loaded["game"]),
            "collection_id": loaded["row"].get("id"),
            "play_records_id": (stats or {}).get("id"),
            "shared_with_copies": (stats or {}).get("collection_games"),
            "categories": [_summarize(c) for c in (stats or {}).get("categories") or []],
            "category_types": list(PLAY_RECORD_TYPES),
        }
    )


async def set_play_record_category(
    slug: str,
    name: str,
    type: str = "",
    layout: str = "",
    template: str = "",
    category_id: str = "",
    confirm_new: bool = False,
    collection_id: str = "",
    parent: str = "",
    rename: str = "",
    description_available: str = "",
    date_available: str = "",
    table_columns: str = "",
    wait_ms: int = 0,
) -> str:
    """Add a Play Records category to one copy, or edit an existing one (matched by name or category_id). type (new categories, default keyValue): keyValue, checkbox, progress, table, text. layout: 1 or 2 columns. parent: put it under another category. rename: new name for an existing category. description_available / date_available: true/false to show those row fields. table_columns: column count for a new table. Categories belong to this copy only, not your profile."""
    del confirm_new, wait_ms
    if template:
        return _dumps(
            {
                "error": "template_not_supported",
                "hint": "Templates import synced store achievements. Create a checkbox category and add rows instead.",
            }
        )
    type_id = normalize_play_record_type(type) if type else None
    if type and not type_id:
        return _dumps({"error": "unknown_type", "type": type, "allowed": list(PLAY_RECORD_TYPES)})
    if not (name or "").strip() and not category_id:
        return _dumps({"error": "name_required"})
    try:
        columns = max(1, min(int(layout), 2)) if str(layout).strip() else None
    except ValueError:
        return _dumps({"error": "invalid_layout", "allowed": [1, 2]})
    page = await _ensure_browser()
    loaded = await _load(page, slug, collection_id, create=True)
    if loaded.get("error"):
        return _dumps(loaded)
    stats = loaded["stats"]
    existing = _find_category(stats, category_id or name)
    flags: dict[str, Any] = {}
    for key, val in (("description_available", description_available), ("date_available", date_available)):
        if str(val).strip():
            flags[key] = str(val).strip().lower() in _TRUE
    if existing:
        body = {**existing, **flags, "columns": columns or existing.get("columns")}
        if rename.strip():
            body["name"] = rename.strip()
        if type_id and type_id != existing.get("type"):
            return _dumps({"error": "type_change_not_supported", "current": existing.get("type")})
        body.pop("children", None)
        result = await ib_api(
            page, "PUT", f"/user_collection_gameplay_stats/{int(stats['id'])}/categories/{int(existing['id'])}", body=body
        )
        if not result.get("ok"):
            return _dumps(api_error(result, "update_category"))
        return _dumps({"ok": True, "status": "updated", "category": _summarize(result.get("data") or body)})
    parent_id = None
    siblings = stats.get("categories") or []
    if parent.strip():
        parent_cat = _find_category(stats, parent)
        if not parent_cat:
            return _dumps({"error": "parent_not_found", "parent": parent})
        parent_id = parent_cat["id"]
        siblings = parent_cat.get("children") or []
    body = _empty_category(name.strip(), type_id or "keyValue", columns or 1, len(siblings) + 1, parent_id)
    body.update(flags)
    if body["type"] == "text":
        body["data"] = [{"content": "", "order": 1}]
    if body["type"] == "table":
        try:
            ncols = max(1, int(table_columns or 2))
        except ValueError:
            ncols = 2
        body["data"] = [{"values": [""] * ncols, "order": 1}]
    result = await ib_api(page, "POST", f"/user_collection_gameplay_stats/{int(stats['id'])}/categories", body=body)
    if not result.get("ok"):
        return _dumps(api_error(result, "add_category"))
    return _dumps(
        {
            "ok": True,
            "status": "created",
            "play_records_id": stats["id"],
            "category": _summarize(result.get("data") or body),
        }
    )


async def set_play_record(
    slug: str,
    category: str,
    action: str = "add",
    name: str = "",
    value: str = "",
    row_index: str = "",
    collection_id: str = "",
    unlocked: str = "",
    progress_earned: str = "",
    progress_total: str = "",
    description: str = "",
    earned_date: str = "",
    values: str = "",
    content: str = "",
    wait_ms: int = 0,
) -> str:
    """Add or update one row in a Play Records category. action: add or update (update needs row_index, 1-based, or a matching name).
    keyValue: name + value. checkbox: name + unlocked=true/false (value=true also works). progress: name + progress_earned/progress_total (or value "3/10"), optional description. table: values as JSON array or "a | b | c". text: content (or value). earned_date YYYY-MM-DD where the category allows dates."""
    del wait_ms
    act = (action or "add").strip().lower()
    if act not in ("add", "update"):
        return _dumps({"error": "unknown_action", "allowed": ["add", "update"]})
    page = await _ensure_browser()
    loaded = await _load(page, slug, collection_id)
    if loaded.get("error"):
        return _dumps(loaded)
    stats = loaded.get("stats")
    if not stats:
        return _dumps({"error": "no_play_records", "hint": "Create a category first with set_play_record_category."})
    cat = _find_category(stats, category)
    if not cat:
        return _dumps({"error": "category_not_found", "category": category, "have": [c.get("name") for c in _walk(stats.get("categories") or [])]})
    fields: dict[str, Any] = {
        "name": name if name != "" else None,
        "value": value if value != "" else None,
        "unlocked": (str(unlocked).strip().lower() in _TRUE) if str(unlocked).strip() else None,
        "progress_earned": progress_earned if str(progress_earned).strip() else None,
        "progress_total": progress_total if str(progress_total).strip() else None,
        "description": description if description != "" else None,
        "earned_date": earned_date if earned_date != "" else None,
        "values": _parse_values(values) if values else None,
        "content": content if content != "" else None,
    }
    data = [dict(r) for r in cat.get("data") or [] if isinstance(r, dict)]
    ctype = str(cat.get("type"))
    if act == "add":
        if ctype == "text" and data:
            return _dumps({"error": "text_has_one_row", "hint": "Use action=update row_index=1 for a text category."})
        new = _row_for(ctype, {"order": len(data) + 1}, fields)
        data.append(new)
        touched = len(data)
    else:
        idx = None
        if str(row_index).strip():
            idx = int(row_index)
        elif name:
            for i, r in enumerate(data, start=1):
                if str(r.get("name") or "").casefold() == name.casefold():
                    idx = i
                    break
        if not idx or idx < 1 or idx > len(data):
            return _dumps({"error": "row_not_found", "rows": len(data)})
        data[idx - 1] = _row_for(ctype, data[idx - 1], fields)
        touched = idx
    body = {**cat, "data": data}
    body.pop("children", None)
    result = await ib_api(
        page, "PUT", f"/user_collection_gameplay_stats/{int(stats['id'])}/categories/{int(cat['id'])}", body=body
    )
    if not result.get("ok"):
        return _dumps(api_error(result, "set_play_record"))
    return _dumps({"ok": True, "action": act, "row": touched, "category": _summarize(result.get("data") or body)})


async def remove_play_record(
    slug: str,
    category: str,
    row_index: str = "",
    confirm: bool = False,
    collection_id: str = "",
    wait_ms: int = 0,
) -> str:
    """Remove one row (row_index, 1-based) from a Play Records category, or the whole category when row_index is empty (needs confirm=true)."""
    del wait_ms
    if not str(row_index).strip() and not confirm:
        return _dumps({"error": "confirm_required", "hint": "Pass confirm=true to delete a whole Play Records category."})
    page = await _ensure_browser()
    loaded = await _load(page, slug, collection_id)
    if loaded.get("error"):
        return _dumps(loaded)
    stats = loaded.get("stats")
    cat = _find_category(stats or {}, category) if stats else None
    if not cat:
        return _dumps({"error": "category_not_found", "category": category})
    base = f"/user_collection_gameplay_stats/{int(stats['id'])}/categories/{int(cat['id'])}"
    if not str(row_index).strip():
        result = await ib_api(page, "DELETE", base)
        if not result.get("ok"):
            return _dumps(api_error(result, "delete_category"))
        return _dumps({"ok": True, "status": "category_deleted", "category": cat.get("name")})
    data = [dict(r) for r in cat.get("data") or [] if isinstance(r, dict)]
    idx = int(row_index)
    if idx < 1 or idx > len(data):
        return _dumps({"error": "row_not_found", "rows": len(data)})
    removed = data.pop(idx - 1)
    for i, r in enumerate(data, start=1):
        r["order"] = i
    body = {**cat, "data": data}
    body.pop("children", None)
    result = await ib_api(page, "PUT", base, body=body)
    if not result.get("ok"):
        return _dumps(api_error(result, "remove_play_record"))
    return _dumps({"ok": True, "status": "row_removed", "removed": removed, "category": _summarize(result.get("data") or body)})


def _pair_rows(ctx: dict[str, Any], from_id: str, to_id: str) -> tuple[dict | None, dict | None, dict | None]:
    """(source row, target row, error) for two copies of the same game."""
    src = next((r for r in ctx["rows"] if str(r.get("id")) == str(from_id).strip()), None)
    dst = next((r for r in ctx["rows"] if str(r.get("id")) == str(to_id).strip()), None)
    if not src or not dst:
        return None, None, {
            "error": "collection_id_not_found",
            "from_collection_id": from_id,
            "to_collection_id": to_id,
            "copies": [slim_collection_row(r) for r in ctx["rows"]],
        }
    return src, dst, None


def _member_id(item: Any) -> str:
    return str(item.get("id") if isinstance(item, dict) else item)


async def copy_play_records(slug: str, from_collection_id: str, to_collection_id: str) -> str:
    """Copy the Play Records of one copy to another copy of the same game. The target must have no Play Records yet."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    src, dst, err = _pair_rows(ctx, from_collection_id, to_collection_id)
    if err:
        return _dumps(err)
    sid = src.get("gameplay_stats_id")
    if not sid:
        return _dumps({"error": "no_play_records", "hint": "The source copy has no Play Records to copy."})
    if dst.get("gameplay_stats_id"):
        return _dumps({"error": "target_has_play_records", "hint": "Copy only into a copy with no Play Records yet."})
    result = await ib_api(
        page,
        "POST",
        f"/user_collection_gameplay_stats/{int(sid)}/copy",
        body={"user_collection_id": int(dst["id"])},
    )
    if not result.get("ok"):
        return _dumps(api_error(result, "copy_play_records"))
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return _dumps(
        {
            "ok": True,
            "status": "copied",
            "from_collection_id": src["id"],
            "to_collection_id": dst["id"],
            "play_records_id": data.get("id"),
        }
    )


async def share_play_records(slug: str, from_collection_id: str, to_collection_id: str, share: bool = True) -> str:
    """Share the Play Records of one copy with another copy of the same game (share=true), or stop sharing with that copy (share=false)."""
    page = await _ensure_browser()
    ctx = await game_context(page, slug, need_row=False)
    if ctx.get("error"):
        return _dumps(ctx)
    src, dst, err = _pair_rows(ctx, from_collection_id, to_collection_id)
    if err:
        return _dumps(err)
    sid = src.get("gameplay_stats_id")
    if not sid:
        return _dumps({"error": "no_play_records", "hint": "The source copy has no Play Records to share."})
    if share and dst.get("gameplay_stats_id") and str(dst["gameplay_stats_id"]) != str(sid):
        return _dumps({"error": "target_has_play_records", "hint": "The target copy already has its own Play Records."})
    if not share and str(dst["id"]) == str(src["id"]):
        return _dumps({"error": "cannot_unshare_source", "hint": "The source copy always keeps its own Play Records."})
    got = await ib_api(page, "GET", f"/user_collection_gameplay_stats/{int(sid)}")
    if not got.get("ok"):
        return _dumps(api_error(got, "share_play_records"))
    stats = got.get("data") if isinstance(got.get("data"), dict) else {}
    members = list(stats.get("collection_games") or [])
    to_key = str(dst["id"])
    if share:
        if not any(_member_id(m) == to_key for m in members):
            members.append(int(dst["id"]))
    else:
        members = [m for m in members if _member_id(m) != to_key]
    result = await ib_api(
        page,
        "PATCH",
        f"/user_collection_gameplay_stats/{int(sid)}",
        body={**stats, "collection_games": members},
    )
    if not result.get("ok"):
        return _dumps(api_error(result, "share_play_records"))
    return _dumps(
        {
            "ok": True,
            "status": "shared" if share else "unshared",
            "play_records_id": int(sid),
            "to_collection_id": dst["id"],
            "shared_with": [_member_id(m) for m in members],
        }
    )


def register(mcp) -> None:
    mcp.tool()(locked_tool(list_play_records))
    mcp.tool()(locked_tool(set_play_record_category))
    mcp.tool()(locked_tool(set_play_record))
    mcp.tool()(locked_tool(remove_play_record))
    mcp.tool()(locked_tool(copy_play_records))
    mcp.tool()(locked_tool(share_play_records))
