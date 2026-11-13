"""Name matching for DLC, tags and list entries."""
from __future__ import annotations

import json
import re


def _normalize_name(name: str, parent_title: str = "") -> str:
    s = (name or "").lower().replace("’", "'")
    s = s.replace("reticle", "reticule")
    s = re.sub(r"\s+", " ", s).strip()
    prefixes = [
        "tomb raider:",
        "tomb raider -",
        "tomb raider ",
    ]
    if parent_title:
        pt = parent_title.lower().strip()
        prefixes.extend([pt + ":", pt + " -", pt + " "])
    for prefix in prefixes:
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()
            break
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(skin|pack|dlc|addon|add on|bonus content|bonus|content)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _names_match(query: str, candidate: str, parent_title: str = "") -> bool:
    q = _normalize_name(query, parent_title)
    c = _normalize_name(candidate, parent_title)
    if not q or not c:
        return False
    if q == c:
        return True
    if q in c or c in q:
        return True
    qt = set(q.split())
    ct = set(c.split())
    if not qt or not ct:
        return False
    shorter, longer = (qt, ct) if len(qt) <= len(ct) else (ct, qt)
    return shorter <= longer


def _parse_names(names: str) -> list[str]:
    raw = (names or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    if "\n" in raw:
        return [ln.strip().strip(",").strip() for ln in raw.splitlines() if ln.strip()]
    return [raw]
