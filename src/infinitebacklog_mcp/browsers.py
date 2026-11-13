"""Find browsers this server may use, without assuming any brand.

Nothing here launches or attaches to a browser. It only lists candidates:

- attach:  an already-open browser that exposes a local debug port (IB_CDP_URL or 127.0.0.1:9222)
- launch:  a Chromium-family browser that is running or set as the system default,
           started with this server's own private profile
- bundled: Playwright's own Chromium

Chromium-family is detected by a generic marker (*.pak resource files next to the
executable), not by name. Labels show the executable file name only, never a path.
The user picks one before anything opens; see browser.py.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess  # nosec B404 - fixed argument lists only, never a shell
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_DEBUG_URL = "http://127.0.0.1:9222"


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: str  # attach | launch | bundled
    label: str
    exe: Optional[str] = None  # kept in memory only; never returned to the client
    endpoint: Optional[str] = None

    def public(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "label": self.label}


# --- Chromium-family check -------------------------------------------------


_VERSION_DIR = re.compile(r"^\d+(\.\d+)+$")


def is_chromium_family(exe: str | os.PathLike | None) -> bool:
    """True for a Chromium-based browser: resource packs (*.pak) beside the executable or in
    its version folder, and no Electron app bundle (resources/*.asar)."""
    if not exe:
        return False
    path = Path(exe)
    if not path.is_file():
        return False
    root = path.parent
    if sys.platform == "darwin":
        bundle = next((p for p in path.parents if p.suffix == ".app"), None)
        if not bundle:
            return False
        root = bundle / "Contents"
        try:
            if any(root.glob("Resources/*.asar")):
                return False
            return any(root.glob("Frameworks/*/Resources/*.pak")) or any(
                root.glob("Frameworks/*/Versions/*/Resources/*.pak")
            )
        except OSError:
            return False
    try:
        if any(root.glob("resources/*.asar")):
            return False
        if any(root.glob("*.pak")):
            return True
        return any(d.is_dir() and _VERSION_DIR.match(d.name) and any(d.glob("*.pak")) for d in root.iterdir())
    except OSError:
        return False


def _registered_browsers_windows() -> set[str]:
    """Executables Windows lists as web browsers (the StartMenuInternet registry key)."""
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return set()
    found: set[str] = set()
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Clients\StartMenuInternet") as root:
                for i in range(winreg.QueryInfoKey(root)[0]):
                    name = winreg.EnumKey(root, i)
                    try:
                        with winreg.OpenKey(root, rf"{name}\shell\open\command") as cmd:
                            exe = exe_from_command(str(winreg.QueryValueEx(cmd, "")[0]))
                    except OSError:
                        continue
                    if exe:
                        found.add(os.path.normcase(exe))
        except OSError:
            continue
    return found


# --- running browsers ------------------------------------------------------


def _run(args: list[str], timeout: float = 10.0) -> str:
    try:
        done = subprocess.run(  # nosec B603 - fixed argv, no shell
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout or ""


def _running_executables() -> list[str]:
    if sys.platform == "win32":
        out = _run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | "
                "Select-Object -ExpandProperty Path -Unique",
            ]
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    if sys.platform.startswith("linux"):
        found = []
        for entry in Path("/proc").glob("[0-9]*/exe"):
            try:
                found.append(str(entry.resolve()))
            except OSError:
                continue
        return found
    if sys.platform == "darwin":
        out = _run(["ps", "-axo", "comm="])
        return [line.strip() for line in out.splitlines() if line.strip().startswith("/")]
    return []


def running_browsers() -> list[str]:
    registered = _registered_browsers_windows() if sys.platform == "win32" else set()
    seen: dict[str, str] = {}
    for exe in _running_executables():
        key = os.path.normcase(exe)
        if key in seen or (registered and key not in registered):
            continue
        if is_chromium_family(exe):
            seen[key] = exe
    return list(seen.values())


# --- default browser -------------------------------------------------------


def exe_from_command(command: str) -> Optional[str]:
    """First token of an 'open' command line or .desktop Exec= value."""
    raw = (command or "").strip()
    if not raw:
        return None
    if raw.startswith('"'):
        end = raw.find('"', 1)
        return raw[1:end] if end > 1 else None
    try:
        parts = shlex.split(raw, posix=not sys.platform.startswith("win"))
    except ValueError:
        parts = raw.split()
    return parts[0] if parts else None


def _default_windows() -> Optional[str]:
    try:
        import winreg  # noqa: PLC0415
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
    except OSError:
        return None
    return exe_from_command(str(command))


def exec_from_desktop_file(text: str) -> Optional[str]:
    for line in (text or "").splitlines():
        if line.startswith("Exec="):
            command = re.sub(r"%[a-zA-Z]", "", line[5:])
            return exe_from_command(command)
    return None


def _default_linux() -> Optional[str]:
    name = _run(["xdg-settings", "get", "default-web-browser"]).strip()
    if not name.endswith(".desktop"):
        return None
    dirs = [Path.home() / ".local/share/applications", Path("/usr/share/applications"), Path("/usr/local/share/applications")]
    for folder in dirs:
        desktop = folder / name
        if desktop.is_file():
            exe = exec_from_desktop_file(desktop.read_text(encoding="utf-8", errors="replace"))
            if exe and not os.path.isabs(exe):
                exe = _which(exe)
            return exe
    return None


def _which(name: str) -> Optional[str]:
    from shutil import which

    return which(name)


def default_browser() -> Optional[str]:
    if sys.platform == "win32":
        return _default_windows()
    if sys.platform.startswith("linux"):
        return _default_linux()
    return None


# --- open browser with a debug port ---------------------------------------


def is_local_endpoint(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "ws"} or parsed.username or parsed.password:
        return False
    return (parsed.hostname or "").lower().strip("[]") in _LOCAL_HOSTS


def debug_endpoint() -> Optional[str]:
    """A local debug endpoint that answers /json/version, or None."""
    raw = (os.environ.get("IB_CDP_URL") or "").strip() or DEFAULT_DEBUG_URL
    if "://" not in raw:
        raw = "http://" + raw
    if not is_local_endpoint(raw):
        return None
    base = raw.rstrip("/")
    if base.startswith("ws://"):
        return base
    try:
        with urllib.request.urlopen(f"{base}/json/version", timeout=1.5) as resp:  # nosec B310 - local http only
            data: Any = json.loads(resp.read().decode("utf-8", "replace"))
    except (OSError, ValueError):
        return None
    ws = str((data or {}).get("webSocketDebuggerUrl") or "")
    return base if ws and is_local_endpoint(ws) else None


# --- candidates ------------------------------------------------------------


def _label(exe: str) -> str:
    return Path(exe).name


def candidates() -> list[Candidate]:
    out: list[Candidate] = []
    endpoint = debug_endpoint()
    if endpoint:
        out.append(
            Candidate(
                "attach",
                "attach",
                "The browser that is already open (uses its real signed-in profile, opens one new tab)",
                endpoint=endpoint,
            )
        )
    explicit = (os.environ.get("IB_BROWSER_PATH") or "").strip()
    default = default_browser()
    running = running_browsers()
    ordered: list[tuple[str, str]] = []
    if explicit:
        ordered.append(("env", explicit))
    if default and is_chromium_family(default):
        ordered.append(("default", default))
    ordered.extend(("running", exe) for exe in running)
    seen: set[str] = set()
    for source, exe in ordered:
        key = os.path.normcase(exe)
        if key in seen:
            continue
        seen.add(key)
        note = {"env": "from IB_BROWSER_PATH", "default": "your default browser", "running": "open now"}[source]
        if source == "default" and key in {os.path.normcase(r) for r in running}:
            note = "your default browser, open now"
        out.append(
            Candidate(
                f"launch-{len(seen)}",
                "launch",
                f"{_label(exe)} ({note}), private profile for this server only",
                exe=exe,
            )
        )
    out.append(Candidate("bundled", "bundled", "Playwright's bundled Chromium, private profile for this server only"))
    out.append(
        Candidate(
            "http",
            "http",
            "No browser: sign in over HTTPS with the IB_USERNAME/IB_PASSWORD account from .env",
        )
    )
    return out


def custom_candidate(path: str) -> Candidate:
    """A browser the user named by path. Must be a Chromium-family executable."""
    exe = (path or "").strip().strip('"')
    if not is_chromium_family(exe):
        raise ValueError("That path is not a Chromium-based browser executable.")
    return Candidate("custom", "launch", f"{_label(exe)} (your choice), private profile for this server only", exe=exe)


def profile_name(candidate: Candidate) -> str:
    """Profile folder per browser binary: Chromium profiles don't move between browsers."""
    if candidate.kind != "launch" or not candidate.exe:
        return "ib-profile"
    stem = re.sub(r"[^A-Za-z0-9_-]", "", Path(candidate.exe).stem.lower()) or "browser"
    return f"ib-profile-{stem}"
