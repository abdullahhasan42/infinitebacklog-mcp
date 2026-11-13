"""Browser detection and the ask-before-opening rule. No browser is started here."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from infinitebacklog_mcp import browser as browser_mod
from infinitebacklog_mcp.browsers import (
    Candidate,
    custom_candidate,
    exe_from_command,
    exec_from_desktop_file,
    is_chromium_family,
    is_local_endpoint,
    profile_name,
)

FAKE = [
    Candidate("launch-1", "launch", "somebrowser.exe (your default browser), private profile", exe="x"),
    Candidate("bundled", "bundled", "Playwright's bundled Chromium, private profile"),
]


def _fake_exe(tmp: str, with_pak: bool) -> str:
    root = Path(tmp)
    exe = root / "browser.exe"
    exe.write_bytes(b"")
    if with_pak:
        (root / "1.2.3").mkdir()
        (root / "1.2.3" / "resources.pak").write_bytes(b"")
    return str(exe)


class DetectionTests(unittest.TestCase):
    def test_chromium_family_is_detected_by_resource_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(is_chromium_family(_fake_exe(tmp, True)))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(is_chromium_family(_fake_exe(tmp, False)))
        self.assertFalse(is_chromium_family(""))
        self.assertFalse(is_chromium_family("does/not/exist.exe"))

    def test_command_parsing(self):
        self.assertEqual(exe_from_command('"C:\\Apps\\b.exe" --single-argument %1'), "C:\\Apps\\b.exe")
        self.assertEqual(exec_from_desktop_file("[Desktop Entry]\nExec=/usr/bin/browser %U\n"), "/usr/bin/browser")
        self.assertIsNone(exe_from_command(""))

    def test_local_endpoints_only(self):
        self.assertTrue(is_local_endpoint("http://127.0.0.1:9222"))
        self.assertFalse(is_local_endpoint("http://example.com:9222"))
        self.assertFalse(is_local_endpoint("http://user:pw@127.0.0.1:9222"))

    def test_profile_is_private_and_per_browser(self):
        self.assertEqual(profile_name(Candidate("bundled", "bundled", "x")), "ib-profile")
        self.assertEqual(profile_name(Candidate("l", "launch", "x", exe="/opt/My Browser!.exe")), "ib-profile-mybrowser")

    def test_custom_path_must_be_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                custom_candidate(_fake_exe(tmp, False))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(custom_candidate(_fake_exe(tmp, True)).kind, "launch")

    def test_public_view_has_no_path(self):
        cand = Candidate("launch-1", "launch", "b.exe (open now)", exe="/home/someone/b.exe")
        self.assertNotIn("exe", cand.public())
        self.assertNotIn("someone", json.dumps(cand.public()))


class ConsentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._saved = (browser_mod._choice, dict(browser_mod._offered), browser_mod._page)
        browser_mod._choice = None
        browser_mod._offered = {}
        browser_mod._page = None
        self._env = patch.dict(os.environ, {"IB_BROWSER": "", "IB_BROWSER_PATH": ""})
        self._env.start()
        self._cands = patch.object(browser_mod, "candidates", lambda: list(FAKE))
        self._cands.start()

    def tearDown(self):
        self._cands.stop()
        self._env.stop()
        browser_mod._choice, browser_mod._offered, browser_mod._page = self._saved

    async def test_nothing_opens_without_a_choice(self):
        launch = AsyncMock()
        with patch.object(browser_mod, "_launch", launch), patch.object(browser_mod, "_attach", launch):
            with self.assertRaises(browser_mod.BrowserChoiceRequired) as ctx:
                await browser_mod._ensure_browser()
        launch.assert_not_called()
        ids = [c["id"] for c in ctx.exception.payload["choices"]]
        self.assertEqual(ids, ["launch-1", "bundled", "other"])

    async def test_wrapped_tool_returns_the_choices(self):
        async def needs_browser():
            await browser_mod._ensure_browser()
            return "opened"

        out = json.loads(await browser_mod.locked_tool(needs_browser)())
        self.assertEqual(out["error"], "browser_choice_required")

    async def test_elicitation_accept_and_decline(self):
        accepted = SimpleNamespace(action="accept", data=SimpleNamespace(choice="bundled", path=""))
        ctx = SimpleNamespace(elicit=AsyncMock(return_value=accepted))
        token = browser_mod._request_ctx.set(ctx)
        try:
            picked = await browser_mod._resolve_choice()
        finally:
            browser_mod._request_ctx.reset(token)
        self.assertEqual(picked.id, "bundled")

        browser_mod._choice = None
        ctx = SimpleNamespace(elicit=AsyncMock(return_value=SimpleNamespace(action="decline")))
        token = browser_mod._request_ctx.set(ctx)
        try:
            with self.assertRaises(browser_mod.SecurityError) as err:
                await browser_mod._resolve_choice()
        finally:
            browser_mod._request_ctx.reset(token)
        self.assertEqual(err.exception.code, "browser_not_approved")
        self.assertIsNone(browser_mod._choice)

    async def test_client_without_elicitation_falls_back(self):
        ctx = SimpleNamespace(elicit=AsyncMock(side_effect=RuntimeError("not supported")))
        token = browser_mod._request_ctx.set(ctx)
        try:
            with self.assertRaises(browser_mod.BrowserChoiceRequired):
                await browser_mod._resolve_choice()
        finally:
            browser_mod._request_ctx.reset(token)

    async def test_choose_browser_validates(self):
        await browser_mod.list_choices()
        with self.assertRaises(ValueError):
            browser_mod.set_choice("nope")
        with self.assertRaises(ValueError):
            browser_mod.set_choice("other", "missing.exe")
        self.assertEqual(browser_mod.set_choice("bundled").kind, "bundled")

    async def test_pre_approval_skips_the_question(self):
        with patch.dict(os.environ, {"IB_BROWSER": "bundled"}):
            self.assertEqual((await browser_mod._resolve_choice()).id, "bundled")


class HtmlSafetyTests(unittest.TestCase):
    def test_unsafe_html_is_escaped(self):
        from infinitebacklog_mcp.normalize import text_to_html

        self.assertEqual(text_to_html("<p>ok <b>bold</b></p>"), "<p>ok <b>bold</b></p>")
        for bad in ("<p>x</p><script>alert(1)</script>", '<p onclick="x()">x</p>', '<p><a href="javascript:x">x</a></p>'):
            with self.subTest(bad=bad):
                out = text_to_html(bad)
                self.assertNotIn("<script", out)
                self.assertTrue(out.startswith("<p>&lt;"))


if __name__ == "__main__":
    unittest.main()
