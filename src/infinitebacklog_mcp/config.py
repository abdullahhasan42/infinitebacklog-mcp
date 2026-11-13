"""Constants, environment helpers, and stderr logging."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

IB_ORIGIN = "https://infinitebacklog.net"

# IB v2.1.0 (Nov 2026): Vue 3 + Tailwind rewrite. The SPA talks to a same-origin JSON API
# under /api with a Keycloak Bearer token. Tools read and write through that API.
SITE_VERSION = "2.1.0"
API_PREFIX = "/api"

# IGDB game categories as used by /api/games/{id}/categories?category[]=N
GAME_CATEGORIES = {
    0: "main_game",
    1: "dlc",
    2: "expansion",
    3: "bundle",
    4: "standalone_expansion",
    5: "mod",
    6: "episode",
    7: "season",
    8: "remake",
    9: "remaster",
    10: "expanded_game",
    11: "port",
    12: "fork",
    13: "pack",
    14: "update",
}
# Additions the collection modal lists under DLC & expansions (completion tracked) ...
DLC_CATEGORIES = frozenset({1, 2, 4, 6, 7})
# ... and under packs / add-ons (no completion).
ADDON_CATEGORIES = frozenset({5, 13, 14})
EDITION_CATEGORIES = frozenset({3})


RATING_SCORE_LABELS = {
    1: "Disaster",
    2: "Painful",
    3: "Awful",
    4: "Bad",
    5: "Mediocre",
    6: "Okay",
    7: "Good",
    8: "Great",
    9: "Amazing",
    10: "Masterpiece",
}


STATUS_ALIASES = {
    "nostatus": "noStatus",
    "no status": "noStatus",
    "unplayed": "unplayed",
    "playing": "playing",
    "played": "played",
}

STATUS_NAMES = {
    "noStatus": "No Status",
    "unplayed": "Unplayed",
    "playing": "Playing",
    "played": "Played",
}

COMPLETION_ALIASES = {
    "nostatus": "noStatus",
    "no status": "noStatus",
    "notstarted": "notStarted",
    "not started": "notStarted",
    "unfinished": "unfinished",
    "beaten": "campaignCompleted",
    "campaigncompleted": "campaignCompleted",
    "completed": "completed",
    "continuous": "continuous",
    "dropped": "dropped",
}

COMPLETION_NAMES = {
    "noStatus": "No Status",
    "notStarted": "Not Started",
    "unfinished": "Unfinished",
    "campaignCompleted": "Beaten",
    "completed": "Completed",
    "continuous": "Continuous",
    "dropped": "Dropped",
}

ACQUISITION_NAMES = {
    "purchase": "Purchase",
    "subscription": "Subscription",
    "gift": "Gift",
    "trade": "Trade",
    "keyBundle": "Key Bundle",
    "promotionalCopy": "Promotional Copy",
    "reviewCopy": "Review Copy",
    "free": "Free",
    "freeToPlay": "Free-to-play",
}

ACQUISITION_ALIASES = {
    "purchase": "purchase",
    "bought": "purchase",
    "buy": "purchase",
    "gift": "gift",
    "gifted": "gift",
    "trade": "trade",
    "key bundle": "keyBundle",
    "keybundle": "keyBundle",
    "promotional copy": "promotionalCopy",
    "promotionalcopy": "promotionalCopy",
    "review copy": "reviewCopy",
    "reviewcopy": "reviewCopy",
    "free": "free",
    "free to play": "freeToPlay",
    "freetoplay": "freeToPlay",
    "free-to-play": "freeToPlay",
    "subscription": "subscription",
    "game pass": "subscription",
}

OWNERSHIP_NAMES = {
    "owned": "Owned",
    "household": "Shared (household)",
    "subscription": "Subscription",
    "borrowed": "Borrowed",
    "rented": "Rented",
    "unlicensed": "Unlicensed",
    "formerlyOwned": "Formerly owned",
    "other": "Other",
    "lentOut": "Lent out",
}
OWNERSHIP_ALIASES = {
    "owned": "owned",
    "own": "owned",
    "household": "household",
    "shared": "household",
    "family": "household",
    "subscription": "subscription",
    "borrowed": "borrowed",
    "rented": "rented",
    "unlicensed": "unlicensed",
    "formerly owned": "formerlyOwned",
    "formerlyowned": "formerlyOwned",
    "sold": "formerlyOwned",
    "other": "other",
    "lent out": "lentOut",
    "lentout": "lentOut",
}

DIGITAL_STORE_NAMES = {
    "steam": "Steam",
    "epicGameStore": "Epic Games",
    "gog": "GOG",
    "xboxLive": "Xbox",
    "uplay": "Ubisoft Connect",
    "rockstarStore": "Rockstar Games",
    "battleNetShop": "Battle.net",
    "origin": "EA",
    "itchIo": "itch.io",
    "discord": "Discord",
    "indieGala": "IndieGala",
    "nutaku": "Nutaku",
    "amazon": "Amazon",
    "bigFish": "Big Fish",
    "legacyGames": "Legacy Games",
    "stove": "Stove",
    "flashpoint": "Flashpoint",
    "psn": "PlayStation Store",
    "nintendoEShop": "Nintendo eShop",
    "wiiShop": "Wii Shop",
    "appleAppStore": "Apple App Store",
    "googlePlayStore": "Google Play",
    "retroAchievement": "RetroAchievements",
    "macAppStore": "Mac App Store",
    "humble": "Humble",
    "metaStore": "Meta Store",
    "other": "Other",
}

PLAY_RECORD_TYPES = ("keyValue", "checkbox", "progress", "table", "text")
PLAY_RECORD_TYPE_ALIASES = {
    "keyvalue": "keyValue",
    "key-value": "keyValue",
    "key value": "keyValue",
    "key-value pair": "keyValue",
    "key value pair": "keyValue",
    "checkbox": "checkbox",
    "progress": "progress",
    "table": "table",
    "text": "text",
    "note": "text",
    "notes": "text",
    "achievements": "checkbox",
    "list": "keyValue",
}

PLAYTHROUGH_TYPES = (
    "firstPlaythrough",
    "replay",
    "speedrun",
    "coop",
    "competitive",
    "continuous",
    "streaming",
    "achievements",
    "challengeRun",
)
PLAYTHROUGH_TYPE_ALIASES = {
    "first": "firstPlaythrough",
    "first playthrough": "firstPlaythrough",
    "firstplaythrough": "firstPlaythrough",
    "replay": "replay",
    "speedrun": "speedrun",
    "coop": "coop",
    "co-op": "coop",
    "competitive": "competitive",
    "continuous": "continuous",
    "streaming": "streaming",
    "achievements": "achievements",
    "achievement hunt": "achievements",
    "challenge": "challengeRun",
    "challenge run": "challengeRun",
    "challengerun": "challengeRun",
}
PLAYTHROUGH_PLAYTIME_TYPES = ("session", "playthrough")
SESSION_STATUSES = ("start", "playing", "campaignCompleted", "completed", "shelved", "dropped")
SESSION_STATUS_ALIASES = {
    "start": "start",
    "started": "start",
    "playing": "playing",
    "beaten": "campaignCompleted",
    "campaigncompleted": "campaignCompleted",
    "completed": "completed",
    "shelved": "shelved",
    "paused": "shelved",
    "dropped": "dropped",
}

REVIEW_MIN_PUBLISH_CHARS = 800


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def default_headless() -> bool:
    """IB v2 renders a blank page in headless Chromium, so the window is visible by default."""
    return env_bool("IB_HEADLESS", False)


def viewport() -> dict[str, int]:
    width = env_int("IB_VIEWPORT_WIDTH", 1280)
    height = env_int("IB_VIEWPORT_HEIGHT", 800)
    return {
        "width": max(320, min(width, 3840)),
        "height": max(240, min(height, 2160)),
    }


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return logging.getLogger("infinitebacklog-mcp")


logger = setup_logging()


def project_root() -> Path:
    """Directory that holds pyproject.toml, or the process working directory."""
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").is_file():
        return cwd
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent
    return cwd


def load_project_env(root: Path | None = None) -> None:
    """Read KEY=VALUE lines from the project .env. Existing process values stay."""
    path = (root or project_root()) / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.info("Could not read the project .env file")
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def playwright_profile_dir(name: str = "ib-profile") -> Path:
    """This server's private browser profile. Never the user's everyday profile."""
    path = project_root() / ".playwright" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


load_project_env()
