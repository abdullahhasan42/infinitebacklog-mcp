"""MCP tools: profile and yearly statistics."""
from __future__ import annotations

from ..api import api_error, current_user, ib_api, require_user_error
from ..browser import _ensure_browser, locked_tool
from ..normalize import _dumps
from ..pages import user_id_from_search
from ..security import sanitize_username


async def get_user_stats(username: str = "", year: str = "", month: str = "") -> str:
    """Collection, activity, achievement and rating statistics for you (default) or another public profile. year (and optional month) adds that period's recap."""
    page = await _ensure_browser()
    me = await current_user(page)
    if username.strip():
        name = sanitize_username(username)
        found = await ib_api(page, "GET", "/users", params={"search": name, "limit": 20, "offset": 0})
        uid = user_id_from_search(name, found.get("data"))
        if not uid:
            return _dumps({"error": "user_not_found", "username": name})
    elif me:
        name, uid = me["username"], me["id"]
    else:
        return _dumps(require_user_error())
    out: dict = {"user": name, "user_id": uid}
    for key, path in (
        ("overview", f"/users/{uid}/statistics"),
        ("profile", f"/users/{uid}/statistics/profile"),
        ("ratings", f"/users/{uid}/statistics/rating"),
    ):
        result = await ib_api(page, "GET", path)
        out[key] = result.get("data") if result.get("ok") else api_error(result, key)
    if str(year).strip():
        params = {"year": int(year)}
        if str(month).strip():
            params["month"] = int(month)
        result = await ib_api(page, "GET", f"/users/{uid}/user_collection_statistic", params=params)
        out["period"] = result.get("data") if result.get("ok") else api_error(result, "period")
    return _dumps(out, limit=30000)


def register(mcp) -> None:
    mcp.tool()(locked_tool(get_user_stats))
