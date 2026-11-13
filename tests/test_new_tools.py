"""Pure helpers and the no-browser guard paths of the wishlist, lists and playtime tools."""
from __future__ import annotations

import asyncio
import json
import unittest


class ListBodyTests(unittest.TestCase):
    def test_list_body_defaults_are_a_private_draft(self):
        from infinitebacklog_mcp.tools.lists import list_body

        body = list_body("My picks", "<p>Hi</p>", [{"id": 1, "name": "Hades", "slug": "hades--1"}])
        self.assertIs(body["published"], False)
        self.assertIs(body["post_feed"], False)
        self.assertEqual(body["type"], "personal")
        self.assertEqual(body["title"], "My picks")
        self.assertEqual(body["games"], [{"id": 1, "name": "Hades", "slug": "hades--1", "rank": 1}])
        self.assertIs(body["ranked"], False)
        self.assertEqual(body["sorting"], "list")

    def test_list_body_publish_flags(self):
        from infinitebacklog_mcp.tools.lists import list_body

        body = list_body("T", "", [], ranked=True, publish=True, spoilers=True, mature_content=True)
        self.assertIs(body["published"], True)
        self.assertIs(body["ranked"], True)
        self.assertIs(body["spoilers"], True)
        self.assertIs(body["mature_content"], True)


class PlaytimeBodyTests(unittest.TestCase):
    def test_playtime_body_maps_minutes(self):
        from infinitebacklog_mcp.tools.playtimes import playtime_body

        self.assertEqual(playtime_body(600.0, 900), {"campaign_completed": 600, "completed": 900})
        self.assertEqual(playtime_body(0, 0), {"campaign_completed": 0, "completed": 0})


class ConfirmGuardTests(unittest.TestCase):
    """These paths return before any browser is opened."""

    def test_remove_from_wishlist_needs_confirm(self):
        from infinitebacklog_mcp.tools.wishlist import remove_from_wishlist

        out = json.loads(asyncio.run(remove_from_wishlist("hades--1")))
        self.assertEqual(out["error"], "confirm_required")

    def test_delete_list_needs_confirm(self):
        from infinitebacklog_mcp.tools.lists import delete_list

        out = json.loads(asyncio.run(delete_list("12")))
        self.assertEqual(out["error"], "confirm_required")

    def test_submit_playtime_needs_confirm(self):
        from infinitebacklog_mcp.tools.playtimes import submit_playtime

        out = json.loads(asyncio.run(submit_playtime("hades--1", beaten_hours="10")))
        self.assertEqual(out["error"], "confirm_required")
        self.assertIn("cannot be deleted", out["hint"])

    def test_create_list_rejects_empty_title(self):
        from infinitebacklog_mcp.tools.lists import create_list

        out = json.loads(asyncio.run(create_list("")))
        self.assertEqual(out["error"], "invalid_title")

    def test_create_list_rejects_long_title(self):
        from infinitebacklog_mcp.tools.lists import create_list

        out = json.loads(asyncio.run(create_list("x" * 101)))
        self.assertEqual(out["error"], "invalid_title")


class ParserTests(unittest.TestCase):
    def test_target_game_id_uses_parent_for_versions(self):
        from infinitebacklog_mcp.tools.playtimes import _target_game_id

        self.assertEqual(_target_game_id({"id": 9, "category": 0, "version_parent": {"id": 4}}), 4)
        self.assertEqual(_target_game_id({"id": 9, "category": 1, "version_parent": 4}), 9)
        self.assertEqual(_target_game_id({"id": 9, "category": 0}), 9)

    def test_list_id_must_be_digits(self):
        from infinitebacklog_mcp.tools.lists import _list_id

        self.assertEqual(_list_id(" 12 "), 12)
        self.assertIsNone(_list_id("abc"))
        self.assertIsNone(_list_id(""))

    def test_extra_flag_parsing(self):
        from infinitebacklog_mcp.tools.lists import _flag

        self.assertIs(_flag("TRUE"), True)
        self.assertIs(_flag("false"), False)
        self.assertIsNone(_flag("yes"))


if __name__ == "__main__":
    unittest.main()
