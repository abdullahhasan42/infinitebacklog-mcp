"""Browserless sign-in and API access over plain HTTPS.

Signs in through Infinite Backlog's own Keycloak login form with the standard
authorization-code + PKCE flow (the same form the browser mode fills), then calls
the JSON API with the resulting Bearer token. The client identifies itself honestly
(no browser user agent), solves no captchas and skips no checks: anything other
than the plain login form stops with browser_sign_in_required.

Tokens and the password stay in memory. Nothing is written to disk or logged.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import http.cookiejar
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from .config import IB_ORIGIN, logger
from .security import SecurityError, check_api_call

USER_AGENT = "infinitebacklog-mcp/2.1 (+https://modelcontextprotocol.io)"
REALM = f"{IB_ORIGIN}/auth/realms/ib/protocol/openid-connect"
AUTH_URL = f"{REALM}/auth"
TOKEN_URL = f"{REALM}/token"
LOGIN_ACTION_PREFIX = f"{IB_ORIGIN}/auth/realms/ib/login-actions/"
CLIENT_ID = "web-application"
REDIRECT_URI = f"{IB_ORIGIN}/"
_FORM_RE = re.compile(r'<form[^>]*\bid="kc-form-login"[^>]*\baction="([^"]+)"', re.I | re.S)
_ERROR_RE = re.compile(r"invalid username or password|account is disabled|account is temporarily disabled", re.I)
_REFRESH_MARGIN_S = 60.0


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def login_form_action(page_html: str) -> Optional[str]:
    """The Keycloak login form's action URL, only if it stays on IB's login-actions path."""
    match = _FORM_RE.search(page_html or "")
    if not match:
        return None
    action = html.unescape(match.group(1))
    return action if action.startswith(LOGIN_ACTION_PREFIX) else None


def code_from_redirect(location: str, state: str) -> Optional[str]:
    """The authorization code from IB's redirect, or None if it isn't ours."""
    if not (location or "").startswith(REDIRECT_URI):
        return None
    parsed = urllib.parse.urlparse(location)
    params = urllib.parse.parse_qs(parsed.query or parsed.fragment)
    if (params.get("state") or [""])[0] != state:
        return None
    return (params.get("code") or [None])[0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class HttpSession:
    """API access without a browser. Duck-types the parts of a Playwright page that api.py needs."""

    is_http = True
    url = REDIRECT_URI

    def __init__(self) -> None:
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar), _NoRedirect())
        self._access = ""
        self._refresh = ""
        self._exp = 0.0

    # --- state ------------------------------------------------------------

    @property
    def signed_in(self) -> bool:
        return bool(self._access) and (self._exp - _REFRESH_MARGIN_S > time.time() or bool(self._refresh))

    def forget(self) -> None:
        self._access = self._refresh = ""
        self._exp = 0.0
        self._jar.clear()

    def is_closed(self) -> bool:
        return False

    # --- low-level HTTP ---------------------------------------------------

    def _open(self, url: str, *, data: Optional[bytes] = None, headers: Optional[dict] = None, method: Optional[str] = None):
        if not url.startswith(f"{IB_ORIGIN}/"):
            raise SecurityError("off_origin", "HTTP mode only talks to infinitebacklog.net.")
        req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            resp = self._opener.open(req, timeout=30)  # nosec B310 - https IB origin enforced above
        except urllib.error.HTTPError as exc:
            resp = exc
        body = resp.read() if hasattr(resp, "read") else b""
        return resp.status if hasattr(resp, "status") else resp.code, resp.headers, body

    def _token_request(self, fields: dict[str, str]) -> dict[str, Any]:
        status, _headers, body = self._open(
            TOKEN_URL,
            data=urllib.parse.urlencode(fields).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            data = {}
        if status != 200 or not data.get("access_token"):
            return {"ok": False, "status": status, "error": str(data.get("error") or "token_error")}
        self._access = str(data["access_token"])
        self._refresh = str(data.get("refresh_token") or self._refresh)
        self._exp = time.time() + float(data.get("expires_in") or 300)
        return {"ok": True}

    # --- sign-in ----------------------------------------------------------

    def sign_in(self, username: str, password: str) -> dict[str, Any]:
        """Authorization code + PKCE through IB's login form. Never returns or logs the password."""
        try:
            verifier, challenge = pkce_pair()
            state = secrets.token_urlsafe(16)
            query = urllib.parse.urlencode(
                {
                    "client_id": CLIENT_ID,
                    "redirect_uri": REDIRECT_URI,
                    "response_type": "code",
                    "response_mode": "query",
                    "scope": "openid",
                    "state": state,
                    "nonce": secrets.token_urlsafe(16),
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
            status, headers, body = self._open(f"{AUTH_URL}?{query}", headers={"Accept": "text/html"})
            code = None
            if status in (302, 303) and headers.get("Location"):
                code = code_from_redirect(headers["Location"], state)  # existing SSO session
            if not code:
                action = login_form_action(body.decode("utf-8", "replace"))
                if not action:
                    return {"ok": False, "error": "browser_sign_in_required", "hint": "The sign-in page wasn't the plain login form. Use a browser sign-in mode."}
                form = urllib.parse.urlencode({"username": username, "password": password, "credentialId": ""}).encode()
                status, headers, body = self._open(
                    action, data=form, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html"}, method="POST"
                )
                if status in (302, 303):
                    code = code_from_redirect(headers.get("Location") or "", state)
                if not code:
                    text = body.decode("utf-8", "replace") if body else ""
                    if _ERROR_RE.search(text):
                        return {"ok": False, "error": "login_failed", "hint": "Infinite Backlog did not accept those credentials."}
                    return {"ok": False, "error": "browser_sign_in_required", "hint": "Sign-in needs another step (for example a captcha or 2FA). Use a browser sign-in mode."}
            result = self._token_request(
                {"grant_type": "authorization_code", "client_id": CLIENT_ID, "code": code, "redirect_uri": REDIRECT_URI, "code_verifier": verifier}
            )
            if not result.get("ok"):
                return {"ok": False, "error": "login_failed", "hint": "The sign-in code was not accepted."}
            return {"ok": True}
        except SecurityError:
            raise
        except Exception as exc:  # network errors etc. Never include request data.
            logger.info("HTTP sign-in stopped at %s", type(exc).__name__)
            return {"ok": False, "error": "login_failed", "hint": "Could not reach Infinite Backlog's sign-in service."}
        finally:
            password = ""  # noqa: F841 - drop the reference

    def ensure_fresh(self) -> bool:
        if self._access and self._exp - _REFRESH_MARGIN_S > time.time():
            return True
        if not self._refresh:
            return False
        result = self._token_request({"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": self._refresh})
        if not result.get("ok"):
            self._access = self._refresh = ""
            return False
        return True

    # --- API --------------------------------------------------------------

    def api(self, method: str, path: str, body: Any = None, *, auth: bool = True) -> dict[str, Any]:
        verb, safe_path = check_api_call(method, path)
        headers = {"Accept": "application/json"}
        if auth and self.ensure_fresh():
            headers["Authorization"] = f"Bearer {self._access}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, resp_headers, raw = self._open(f"{IB_ORIGIN}/api{safe_path}", data=data, headers=headers, method=verb)
        if status == 401 and auth and self._refresh:
            self._exp = 0.0
            if self.ensure_fresh():
                headers["Authorization"] = f"Bearer {self._access}"
                status, resp_headers, raw = self._open(f"{IB_ORIGIN}/api{safe_path}", data=data, headers=headers, method=verb)
        text = raw.decode("utf-8", "replace") if raw else ""
        try:
            parsed: Any = json.loads(text) if text else None
        except ValueError:
            parsed = text
        return {"ok": 200 <= status < 300, "status": status, "data": parsed, "total": resp_headers.get("x-total-count")}

    async def api_async(self, method: str, path: str, body: Any = None, *, auth: bool = True) -> dict[str, Any]:
        return await asyncio.to_thread(self.api, method, path, body, auth=auth)

    async def sign_in_async(self, username: str, password: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.sign_in, username, password)

    async def ensure_fresh_async(self) -> bool:
        return await asyncio.to_thread(self.ensure_fresh)
