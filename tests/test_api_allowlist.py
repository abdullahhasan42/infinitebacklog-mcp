"""The v2 API allowlist and the payload builders (no browser)."""
from __future__ import annotations

import unittest

from infinitebacklog_mcp.api import _jwt_exp, api_error, build_path
from infinitebacklog_mcp.security import SecurityError, check_api_call


class AllowlistTests(unittest.TestCase):
    def test_allows_the_calls_the_tools_make(self):
        for method, path in (
            ("GET", "/users/me/complete"),
            ("GET", "/games?query=hades&limit=5"),
            ("GET", "/games/slug/hades--1?expand=full"),
            ("GET", "/games/113112/categories?category%5B%5D=1"),
            ("GET", "/user_collections?user_id=1&game_id=2"),
            ("POST", "/user_collections/bulk"),
            ("DELETE", "/user_collections/123"),
            ("POST", "/user_collections/5/gameplay_stats"),
            ("POST", "/user_collection_gameplay_stats/7/categories"),
            ("PUT", "/user_collection_gameplay_stats/7/categories/9"),
            ("DELETE", "/user_collection_gameplay_stats/7/categories/9"),
            ("POST", "/user_collections/5/playthroughs/init"),
            ("PUT", "/user_collection_playthroughs/3?user_collection_id=5"),
            ("POST", "/user_collection_playthroughs/3/sessions"),
            ("DELETE", "/user_collection_playthroughs/3/sessions/4"),
            ("POST", "/ratings"),
            ("PUT", "/ratings/9"),
            ("POST", "/reviews/"),
            ("GET", "/users/example_user/reviews/hades--1"),
            ("POST", "/user_collection_tags"),
            ("GET", "/api/startup"),
            ("GET", "/user_wishlists?user_id=1&game_id=2"),
            ("POST", "/user_wishlists"),
            ("PUT", "/user_wishlists/5"),
            ("DELETE", "/user_wishlists/game/9"),
            ("GET", "/lists?user_id=1&limit=25"),
            ("POST", "/lists"),
            ("GET", "/lists/3"),
            ("PUT", "/lists/3"),
            ("DELETE", "/lists/3"),
            ("GET", "/user_playtimes?user_id=1&sort_field=updated_at"),
            ("POST", "/user_playtimes"),
            ("PUT", "/user_playtimes/5"),
            ("POST", "/user_collection_gameplay_stats/7/copy"),
            ("PATCH", "/user_collection_gameplay_stats/7"),
        ):
            with self.subTest(method=method, path=path):
                verb, safe = check_api_call(method, path)
                self.assertEqual(verb, method)
                self.assertTrue(safe.startswith("/"))
                self.assertFalse(safe.startswith("/api/"))

    def test_refuses_profile_settings_and_unknown_calls(self):
        for method, path in (
            ("PUT", "/users/1001"),
            ("PUT", "/user_collection_statistic_settings"),
            ("PUT", "/user_collections/bulk/delete"),
            ("POST", "/user_accomplishment_favourites"),
            ("DELETE", "/users/1001"),
            ("POST", "/feed"),
            ("GET", "/admin/users"),
            ("PATCH", "/user_playtimes/ignore"),
            ("DELETE", "/reviews/comments/5"),
            ("POST", "/user_collections"),
            ("DELETE", "/user_wishlists/5"),
            ("DELETE", "/user_playtimes/5"),
        ):
            with self.subTest(method=method, path=path):
                with self.assertRaises(SecurityError) as ctx:
                    check_api_call(method, path)
                self.assertEqual(ctx.exception.code, "api_not_allowed")

    def test_refuses_off_origin_and_traversal(self):
        for path in ("https://evil.example/api", "//evil.example/x", "/games/../users/1", "/http://x"):
            with self.subTest(path=path):
                with self.assertRaises(SecurityError):
                    check_api_call("GET", path)

    def test_refuses_unknown_method(self):
        with self.assertRaises(SecurityError) as ctx:
            check_api_call("OPTIONS", "/games")
        self.assertEqual(ctx.exception.code, "invalid_api_method")


class HelperTests(unittest.TestCase):
    def test_build_path_matches_axios_arrays(self):
        self.assertEqual(
            build_path("/games/1/categories", {"category": [0, 1]}),
            "/games/1/categories?category%5B%5D=0&category%5B%5D=1",
        )
        self.assertEqual(build_path("/x", {"a": None, "b": "", "c": True}), "/x?c=true")

    def test_jwt_exp_reads_payload_only(self):
        import base64
        import json

        payload = base64.urlsafe_b64encode(json.dumps({"exp": 123}).encode()).decode().rstrip("=")
        self.assertEqual(_jwt_exp(f"h.{payload}.sig"), 123.0)
        self.assertEqual(_jwt_exp("garbage"), 0.0)

    def test_api_error_maps_forbidden_to_feature_locked(self):
        out = api_error(
            {"status": 403, "data": {"errors": [{"code": "FORBIDDEN", "property": "role", "message": "no"}]}},
            "create_tag",
        )
        self.assertEqual(out["error"], "feature_locked")
        self.assertEqual(api_error({"status": 401, "data": None}, "x")["error"], "not_logged_in")


class PayloadTests(unittest.TestCase):
    def test_new_row_matches_spa_shape(self):
        from infinitebacklog_mcp.tools.collection import new_row

        row = new_row(113112, 169, digital=False)
        self.assertEqual(row["platform_id"], 169)
        self.assertTrue(row["physical"])
        self.assertEqual(row["additions"], [])
        self.assertEqual(row["playtime_type"], "manual")

    def test_completion_date_types(self):
        from infinitebacklog_mcp.tools.collection import _date_and_type

        self.assertEqual(_date_and_type("2026"), ("2026-01-01", "year"))
        self.assertEqual(_date_and_type("2026-03"), ("2026-03-01", "month"))
        self.assertEqual(_date_and_type("2026-03-09"), ("2026-03-09", "day"))
        with self.assertRaises(ValueError):
            _date_and_type("9 March")

    def test_dlc_tracks_completion_packs_do_not(self):
        from infinitebacklog_mcp.tools.related import _addition_entry

        self.assertEqual(_addition_entry({"id": 5, "category": 1}), {"game_id": 5, "completion": "notStarted"})
        self.assertEqual(_addition_entry({"id": 6, "category": 13}), {"game_id": 6, "completion": None})

    def test_play_record_rows_per_type(self):
        from infinitebacklog_mcp.tools.play_records import _row_for

        kv = _row_for("keyValue", {"order": 1}, {"name": "Boss", "value": "beaten"})
        self.assertEqual((kv["name"], kv["value"]), ("Boss", "beaten"))
        cb = _row_for("checkbox", {"order": 1}, {"name": "Platinum", "value": "yes"})
        self.assertTrue(cb["unlocked"])
        pr = _row_for("progress", {"order": 1}, {"name": "Keys", "value": "3/10"})
        self.assertEqual((pr["progress_earned"], pr["progress_total"]), (3.0, 10.0))
        tb = _row_for("table", {"order": 1}, {"value": "a | b | c"})
        self.assertEqual(tb["values"], ["a", "b", "c"])
        tx = _row_for("text", {"order": 1}, {"content": "<p>hi</p>"})
        self.assertEqual(tx["content"], "<p>hi</p>")

    def test_platform_resolution(self):
        from infinitebacklog_mcp.normalize import resolve_platform

        plats = [
            {"id": 6, "name": "Windows PC", "abbreviation": "PC", "alternative_name": "mswin", "slug": "win"},
            {"id": 167, "name": "PlayStation 5", "abbreviation": "PS5"},
            {"id": 169, "name": "Xbox Series X|S", "abbreviation": "Series X|S", "alternative_name": "XSX"},
        ]
        self.assertEqual(resolve_platform("pc", plats)["id"], 6)
        self.assertEqual(resolve_platform("Windows", plats)["id"], 6)
        self.assertEqual(resolve_platform("PS5", plats)["id"], 167)
        self.assertEqual(resolve_platform("xbox series x", plats)["id"], 169)
        self.assertEqual(resolve_platform("169", plats)["id"], 169)
        self.assertIsNone(resolve_platform("dreamcast", plats))

    def test_text_to_html(self):
        from infinitebacklog_mcp.normalize import html_text_length, text_to_html

        html = text_to_html("One <b>\nline\n\nTwo")
        self.assertEqual(html, "<p>One &lt;b&gt;<br>line</p><p>Two</p>")
        self.assertEqual(html_text_length(html), len("One &lt;b&gt;lineTwo"))
        self.assertEqual(text_to_html("<p>kept</p>"), "<p>kept</p>")


if __name__ == "__main__":
    unittest.main()
