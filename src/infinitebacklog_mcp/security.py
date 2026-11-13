"""Allowlists and sanitizers for Infinite Backlog MCP tool arguments."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

from .config import IB_ORIGIN, env_bool

IB_HOSTS = frozenset({"infinitebacklog.net", "www.infinitebacklog.net"})
SLUG_RE = re.compile(r"^[a-zA-Z0-9]+(?:-{1,2}[a-zA-Z0-9]+)*$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
COLLECTION_ID_RE = re.compile(r"^\d+$")
MAX_WAIT_MS = 30000


class SecurityError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _host_ok(hostname: str | None) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host in IB_HOSTS


def is_ib_origin(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme.lower() != "https":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.port not in (None, 443):
        return False
    return _host_ok(parsed.hostname)


def ib_url_from_path(path: str) -> str:
    """Resolve a tool path to an https://infinitebacklog.net URL. Never pass through caller URLs."""
    raw = (path or "").strip() or "/"
    lowered = raw.lower()
    if lowered.startswith(("javascript:", "file:", "data:", "vbscript:", "about:")):
        raise SecurityError("off_origin", "Refusing non-https navigation.")
    if lowered.startswith("http://") or lowered.startswith("https://"):
        if not is_ib_origin(raw):
            raise SecurityError("off_origin", "Refusing navigation off infinitebacklog.net.")
        parsed = urlparse(raw)
        rel = parsed.path or "/"
        if parsed.query:
            rel += "?" + parsed.query
        raw = rel
    elif raw.startswith("//") or "://" in raw:
        raise SecurityError("off_origin", "Refusing navigation off infinitebacklog.net.")
    if "\\" in raw or "\x00" in raw:
        raise SecurityError("invalid_path", "Invalid navigation path.")
    if not raw.startswith("/"):
        raw = "/" + raw
    parsed = urlparse(IB_ORIGIN + raw)
    rebuilt = urlunparse(("https", "infinitebacklog.net", parsed.path or "/", "", parsed.query, ""))
    if not is_ib_origin(rebuilt):
        raise SecurityError("off_origin", "Refusing navigation off infinitebacklog.net.")
    return rebuilt


def sanitize_slug(slug: str) -> str:
    s = (slug or "").strip().strip("/")
    if s.lower().startswith("http://") or s.lower().startswith("https://"):
        if not is_ib_origin(s):
            raise SecurityError("off_origin", "Refusing a non-IB slug URL.")
        s = urlparse(s).path.strip("/")
    if s.startswith("games/"):
        s = s.split("/", 1)[1]
    if not s or "/" in s or "\\" in s or ".." in s:
        raise SecurityError("invalid_slug", "Invalid game slug.")
    if not SLUG_RE.fullmatch(s):
        raise SecurityError("invalid_slug", "Invalid game slug.")
    return s


def sanitize_username(username: str, *, allow_empty: bool = False) -> str:
    u = (username or "").strip()
    if not u:
        if allow_empty:
            return ""
        raise SecurityError("invalid_username", "Invalid username.")
    if not USERNAME_RE.fullmatch(u):
        raise SecurityError("invalid_username", "Invalid username.")
    return u


def sanitize_collection_id(cid: str, *, allow_empty: bool = True) -> str:
    s = str(cid or "").strip()
    if not s:
        if allow_empty:
            return ""
        raise SecurityError("collection_id_required", "collection_id is required.")
    if not COLLECTION_ID_RE.fullmatch(s):
        raise SecurityError("invalid_collection_id", "collection_id must be digits.")
    return s


# Same-origin API calls the tools may make (IB v2.1.0). Paths are relative to /api, without
# the query string. Anything else is refused before it reaches the page. Profile, settings,
# social, bulk-delete and admin endpoints are deliberately absent.
_N = r"\d+"
API_RULES: dict[str, tuple[str, ...]] = {
    "GET": (
        r"/startup",
        r"/users/me/complete",
        r"/users",
        r"/users/{n}/statistics",
        r"/users/{n}/statistics/profile",
        r"/users/{n}/statistics/rating",
        r"/users/{n}/user_collection_statistic",
        r"/users/[A-Za-z0-9._-]+/reviews/[a-zA-Z0-9-]+",
        r"/games",
        r"/games/slug/[a-zA-Z0-9-]+",
        r"/games/{n}",
        r"/games/{n}/categories",
        r"/games/{n}/ratings",
        r"/user_collections",
        r"/user_collections/statistics",
        r"/user_collections/{n}/playthroughs",
        r"/user_collections/{n}/playtimes",
        r"/user_collection_gameplay_stats/{n}",
        r"/user_collection_playthrough_sessions",
        r"/user_collection_tags",
        r"/ratings",
        r"/reviews",
        r"/accomplishment_games",
        r"/user_accomplishment_games",
        r"/user_accomplishment_games/status",
        r"/user_accomplishments/{n}",
        r"/user_(?:steam|xbox|gog|retro_achievement)_games/[A-Za-z0-9_.-]+/achievements",
        r"/user_psn_games/[A-Za-z0-9_.-]+/trophies",
        r"/purchase_places",
        r"/user_wishlists",
        r"/lists",
        r"/lists/{n}",
        r"/user_playtimes",
    ),
    "POST": (
        r"/user_collections/bulk",
        r"/user_collections/{n}/gameplay_stats",
        r"/user_collection_gameplay_stats/{n}/categories",
        r"/user_collection_gameplay_stats/{n}/copy",
        r"/user_collections/{n}/playthroughs",
        r"/user_collections/{n}/playthroughs/init",
        r"/user_collection_playthroughs/{n}/sessions",
        r"/ratings",
        r"/reviews/?",
        r"/user_collection_tags",
        r"/user_wishlists",
        r"/lists",
        r"/user_playtimes",
    ),
    "PUT": (
        r"/user_collection_gameplay_stats/{n}/categories/{n}",
        r"/user_collection_playthroughs/{n}",
        r"/user_collection_playthroughs/{n}/sessions/{n}",
        r"/ratings/{n}",
        r"/reviews/{n}",
        r"/user_wishlists/{n}",
        r"/lists/{n}",
        r"/user_playtimes/{n}",
    ),
    "PATCH": (
        r"/user_collection_playthroughs/{n}",
        r"/user_collection_gameplay_stats/{n}",
    ),
    "DELETE": (
        r"/user_collections/{n}",
        r"/user_collection_gameplay_stats/{n}",
        r"/user_collection_gameplay_stats/{n}/categories/{n}",
        r"/user_collection_playthroughs/{n}",
        r"/user_collection_playthroughs/{n}/sessions/{n}",
        r"/ratings/{n}",
        r"/reviews/{n}",
        r"/user_collection_tags/{n}",
        r"/user_wishlists/game/{n}",
        r"/lists/{n}",
    ),
}
_API_RULES_RE = {
    method: tuple(re.compile("^" + rule.replace("{n}", _N) + "$") for rule in rules)
    for method, rules in API_RULES.items()
}


def check_api_call(method: str, path: str) -> tuple[str, str]:
    """Validate an API call against the allowlist. Returns (METHOD, /api-relative path?query)."""
    verb = (method or "GET").strip().upper()
    if verb not in _API_RULES_RE:
        raise SecurityError("invalid_api_method", f"API method {verb} is not allowed.")
    raw = (path or "").strip()
    if raw.startswith("/api/"):
        raw = raw[4:]
    if not raw.startswith("/"):
        raw = "/" + raw
    lowered = raw.lower()
    if raw.startswith("//") or "://" in raw or "\\" in raw or "\x00" in raw or lowered.startswith("/http"):
        raise SecurityError("invalid_api_path", "API path must be a same-origin /api path.")
    parsed = urlparse(raw)
    if ".." in parsed.path.split("/"):
        raise SecurityError("invalid_api_path", "API path must stay under /api.")
    if not any(rx.match(parsed.path) for rx in _API_RULES_RE[verb]):
        raise SecurityError(
            "api_not_allowed",
            f"{verb} {parsed.path} is not on this server's allowlist.",
        )
    return verb, parsed.path + (f"?{parsed.query}" if parsed.query else "")


def clamp_wait_ms(value: Any, default: int = 2000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0, min(parsed, MAX_WAIT_MS))


def chromium_launch_args() -> list[str]:
    args = ["--disable-dev-shm-usage"]
    if env_bool("IB_CHROMIUM_NO_SANDBOX", False):
        args.append("--no-sandbox")
    return args
