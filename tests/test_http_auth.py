"""Browserless HTTP sign-in: pure helpers and guards. No network."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from infinitebacklog_mcp import browser as browser_mod
from infinitebacklog_mcp.http_auth import (
    LOGIN_ACTION_PREFIX,
    REDIRECT_URI,
    HttpSession,
    code_from_redirect,
    login_form_action,
    pkce_pair,
)
from infinitebacklog_mcp.security import SecurityError


class PkceTests(unittest.TestCase):
    def test_challenge_is_s256_of_verifier(self):
        verifier, challenge = pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        self.assertGreaterEqual(len(verifier), 43)
        self.assertNotEqual(pkce_pair()[0], verifier)


class LoginFormTests(unittest.TestCase):
    def test_action_must_stay_on_ib_login_actions(self):
        good = f'<form id="kc-form-login" class="x" action="{LOGIN_ACTION_PREFIX}authenticate?session_code=a&amp;tab_id=b" method="post">'
        self.assertEqual(login_form_action(good), f"{LOGIN_ACTION_PREFIX}authenticate?session_code=a&tab_id=b")
        evil = '<form id="kc-form-login" action="https://evil.example/collect" method="post">'
        self.assertIsNone(login_form_action(evil))
        self.assertIsNone(login_form_action("<html>captcha</html>"))

    def test_code_only_from_our_redirect_with_our_state(self):
        self.assertEqual(code_from_redirect(f"{REDIRECT_URI}?state=s1&code=abc", "s1"), "abc")
        self.assertIsNone(code_from_redirect(f"{REDIRECT_URI}?state=other&code=abc", "s1"))
        self.assertIsNone(code_from_redirect("https://evil.example/?state=s1&code=abc", "s1"))


class SessionGuardTests(unittest.TestCase):
    def test_refuses_other_origins(self):
        with self.assertRaises(SecurityError):
            HttpSession()._open("https://evil.example/api/x")

    def test_api_uses_the_allowlist(self):
        with self.assertRaises(SecurityError):
            HttpSession().api("PUT", "/users/1001", {"x": 1})

    def test_failed_sign_in_never_echoes_the_password(self):
        secret = "hunter2-very-secret"
        session = HttpSession()

        def boom(*args, **kwargs):
            raise OSError(f"network down while sending {secret}")

        with patch.object(session, "_open", side_effect=boom):
            out = session.sign_in("someone", secret)
        self.assertFalse(out["ok"])
        self.assertNotIn(secret, json.dumps(out))

    def test_not_signed_in_without_tokens(self):
        session = HttpSession()
        self.assertFalse(session.signed_in)
        self.assertFalse(session.ensure_fresh())


class ChoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved = (browser_mod._choice, dict(browser_mod._offered), browser_mod._page)
        browser_mod._choice = None
        browser_mod._page = None

    def tearDown(self):
        browser_mod._choice, browser_mod._offered, browser_mod._page = self._saved

    async def test_http_mode_is_offered_and_pre_approvable(self):
        from infinitebacklog_mcp.browsers import Candidate

        fake = [
            Candidate("bundled", "bundled", "bundled"),
            Candidate("http", "http", "No browser"),
        ]
        with patch.object(browser_mod, "candidates", lambda: list(fake)), patch.dict(
            os.environ, {"IB_BROWSER": "http", "IB_BROWSER_PATH": "", "IB_USERNAME": "", "IB_PASSWORD": ""}
        ):
            picked = await browser_mod._resolve_choice()
            self.assertEqual(picked.kind, "http")
            session = await browser_mod._ensure_browser()
            self.assertTrue(getattr(session, "is_http", False))
            self.assertEqual(browser_mod.session_details(), "mode=http (no browser)")
            await browser_mod._close_browser()


if __name__ == "__main__":
    unittest.main()
