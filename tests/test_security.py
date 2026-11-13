"""Security allowlists for the Infinite Backlog MCP."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from infinitebacklog_mcp.security import (
    SecurityError,
    chromium_launch_args,
    clamp_wait_ms,
    ib_url_from_path,
    is_ib_origin,
    sanitize_collection_id,
    sanitize_slug,
    sanitize_username,
)


class OriginTests(unittest.TestCase):
    def test_allows_ib_https(self):
        self.assertTrue(is_ib_origin("https://infinitebacklog.net/games/hades"))
        self.assertTrue(is_ib_origin("https://www.infinitebacklog.net/"))
        self.assertEqual(ib_url_from_path("/games"), "https://infinitebacklog.net/games")
        self.assertEqual(
            ib_url_from_path("https://infinitebacklog.net/games/hades--1"),
            "https://infinitebacklog.net/games/hades--1",
        )
        self.assertEqual(
            ib_url_from_path("/games?q=Tomb%20Raider"),
            "https://infinitebacklog.net/games?q=Tomb%20Raider",
        )

    def test_rejects_off_origin_and_schemes(self):
        denied = [
            "https://evil.example/",
            "https://infinitebacklog.net.evil.com/",
            "https://user:pass@infinitebacklog.net/",
            "http://infinitebacklog.net/",
            "http://127.0.0.1:17493/",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "//evil.example/phish",
            "HTTPS://evil.example/",
        ]
        for url in denied:
            with self.subTest(url=url):
                self.assertFalse(is_ib_origin(url))
                with self.assertRaises(SecurityError) as ctx:
                    ib_url_from_path(url)
                self.assertEqual(ctx.exception.code, "off_origin")


class IdentifierTests(unittest.TestCase):
    def test_slug_allows_igdb_style(self):
        self.assertEqual(sanitize_slug("hades--1"), "hades--1")
        self.assertEqual(sanitize_slug("games/hades--1"), "hades--1")
        self.assertEqual(sanitize_slug("tomb-raider"), "tomb-raider")

    def test_slug_rejects_traversal(self):
        for slug in ("../settings", "..", "hades/../settings", "hades/foo", "%2e%2e"):
            with self.subTest(slug=slug):
                with self.assertRaises(SecurityError) as ctx:
                    sanitize_slug(slug)
                self.assertEqual(ctx.exception.code, "invalid_slug")

    def test_username_and_collection_id(self):
        self.assertEqual(sanitize_username("Example_User"), "Example_User")
        self.assertEqual(sanitize_username("", allow_empty=True), "")
        with self.assertRaises(SecurityError):
            sanitize_username("bob/../admin")
        self.assertEqual(sanitize_collection_id("9866217"), "9866217")
        self.assertEqual(sanitize_collection_id("", allow_empty=True), "")
        with self.assertRaises(SecurityError) as ctx:
            sanitize_collection_id("1'; fetch('https://evil.com')")
        self.assertEqual(ctx.exception.code, "invalid_collection_id")


class LimitAndFlagTests(unittest.TestCase):
    def test_wait_ms_clamp(self):
        self.assertEqual(clamp_wait_ms(10**12), 30000)
        self.assertEqual(clamp_wait_ms(-5), 0)
        self.assertEqual(clamp_wait_ms("nope", default=2000), 2000)


    def test_no_sandbox_off_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "IB_CHROMIUM_NO_SANDBOX"}
        with patch.dict(os.environ, env, clear=True):
            self.assertNotIn("--no-sandbox", chromium_launch_args())
        with patch.dict(os.environ, {"IB_CHROMIUM_NO_SANDBOX": "true"}):
            self.assertIn("--no-sandbox", chromium_launch_args())


class ToolEarlyExitTests(unittest.IsolatedAsyncioTestCase):


    async def test_login_failure_hides_password(self):
        from infinitebacklog_mcp.login import login_failure, redact

        secret = "super-secret-password"
        out = login_failure(secret)
        self.assertEqual(out["error"], "login_failed")
        self.assertNotIn(secret, json.dumps(out))
        self.assertEqual(redact(f"fill failed {secret}", secret), "fill failed ")


    async def test_open_site_rejects_off_origin_before_browser(self):
        from infinitebacklog_mcp.tools.navigation import open_site

        with self.assertRaises(SecurityError):
            await open_site("https://evil.example/")

    async def test_related_rejects_evil_slug_before_browser(self):
        from infinitebacklog_mcp.tools.games import list_related_content

        with self.assertRaises(SecurityError):
            await list_related_content("../settings")

    async def test_wrapped_tool_returns_json_for_bad_slug(self):
        from infinitebacklog_mcp.browser import locked_tool
        from infinitebacklog_mcp.tools.collection import set_game_progress

        out = json.loads(await locked_tool(set_game_progress)("../../settings", status="played"))
        self.assertEqual(out["error"], "invalid_slug")


class SignInPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_from_env_does_not_return_the_password(self):
        from infinitebacklog_mcp.login import login_from_env

        secret = "super-secret-password"

        class ExplodingPage:
            url = "https://infinitebacklog.net/"

            async def evaluate(self, *args, **kwargs):
                raise RuntimeError(f"typed {secret} into the field")

            async def goto(self, *args, **kwargs):
                raise RuntimeError(f"typed {secret} into the field")

        env = {"IB_USERNAME": "example_user", "IB_PASSWORD": secret}
        with patch.dict(os.environ, env, clear=False):
            out = await login_from_env(ExplodingPage())
        self.assertFalse(out["ok"])
        self.assertNotIn(secret, json.dumps(out))

    def test_ensure_browser_does_not_attach_or_read_cookies(self):
        import inspect

        from infinitebacklog_mcp.browser import _ensure_browser

        source = inspect.getsource(_ensure_browser)
        self.assertNotIn("_attach_user_browser", source)
        self.assertNotIn("IB_COOKIES", source)
        self.assertNotIn("add_cookies", source)

    def test_login_clicks_the_visible_log_in_control(self):
        import inspect

        from infinitebacklog_mcp.login import _sign_in_button, login_from_env

        self.assertIn("visible=true", inspect.getsource(_sign_in_button))
        self.assertIn("Sign in", inspect.getsource(_sign_in_button))
        self.assertNotIn('page.click(".nav-item.login")', inspect.getsource(login_from_env))

    def test_env_example_has_password_login_and_no_cookie_vars(self):
        from infinitebacklog_mcp.config import project_root

        text = (project_root() / ".env.example").read_text(encoding="utf-8")
        self.assertIn("IB_USERNAME", text)
        self.assertIn("IB_PASSWORD", text)
        self.assertNotIn("IB_COOKIES", text)
        self.assertNotIn("IB_CDP=", text)  # attach is opt-in: only a commented IB_CDP_URL example
        self.assertIn("# IB_CDP_URL=http://127.0.0.1:", text)

    def test_load_project_env_does_not_override(self):
        from infinitebacklog_mcp.config import load_project_env

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "IB_USERNAME=fromfile\nIB_PASSWORD=sekrit\nKEEP=no\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"KEEP": "yes"}, clear=False):
                os.environ.pop("IB_USERNAME", None)
                os.environ.pop("IB_PASSWORD", None)
                try:
                    load_project_env(root)
                    self.assertEqual(os.environ.get("IB_USERNAME"), "fromfile")
                    self.assertEqual(os.environ.get("IB_PASSWORD"), "sekrit")
                    self.assertEqual(os.environ.get("KEEP"), "yes")
                finally:
                    os.environ.pop("IB_USERNAME", None)
                    os.environ.pop("IB_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
