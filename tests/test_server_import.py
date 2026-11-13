"""Smoke tests that load the MCP server without launching a browser."""
from __future__ import annotations

import os
import unittest



class ServerImportTests(unittest.TestCase):
    def test_import_server_without_browser(self) -> None:
        from infinitebacklog_mcp.server import main, mcp

        self.assertTrue(callable(main))
        self.assertEqual(mcp.name, "infinitebacklog")
        self.assertEqual(mcp.version, "2.1.0")

    def test_registered_tools(self) -> None:
        from infinitebacklog_mcp.server import mcp

        tools = mcp._tool_manager._tools
        expected = {
            # session and pages
            "choose_browser", "open_site", "current_url", "close_browser", "login",
            # catalog and games
            "search_games", "get_game", "list_related_content", "get_game_stats", "list_achievements",
            # collection
            "list_collection", "list_collection_game_options", "add_game_to_collection",
            "add_game_platform_copy", "set_game_progress", "set_game_details",
            "set_game_acquisition", "delete_game_copy",
            # wishlist, custom lists, playtime contributions
            "list_wishlist", "add_to_wishlist", "remove_from_wishlist",
            "list_my_lists", "get_list", "create_list", "update_list", "delete_list",
            "list_playtime_contributions", "submit_playtime",
            # play records sharing
            "copy_play_records", "share_play_records",
            # DLC and packs
            "list_collection_content_menus", "add_game_content", "remove_game_content",
            # ratings and reviews
            "set_game_rating", "add_game_review", "delete_game_review",
            # play records
            "list_play_records", "set_play_record_category", "set_play_record", "remove_play_record",
            # playthroughs
            "list_playthroughs", "set_playthrough", "remove_playthrough",
            "add_play_session", "remove_play_session", "get_play_journal",
            # tags and stats
            "list_custom_tags", "set_game_tags", "delete_custom_tag", "get_user_stats",
        }
        self.assertEqual(set(tools), expected)


if __name__ == "__main__":
    unittest.main()
