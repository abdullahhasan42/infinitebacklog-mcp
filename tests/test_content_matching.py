import json
import unittest

from infinitebacklog_mcp.names import _names_match, _normalize_name


PARENT = "Tomb Raider"


class NormalizeTests(unittest.TestCase):
    def test_reticle_to_reticule(self):
        self.assertEqual(
            _normalize_name("Headshot Reticle", PARENT),
            _normalize_name("Tomb Raider: Headshot Reticule", PARENT),
        )

    def test_strips_parent_and_skin(self):
        self.assertEqual(_normalize_name("Tomb Raider: Aviatrix Skin", PARENT), "aviatrix")
        self.assertEqual(_normalize_name("Hunter Skin", PARENT), "hunter")

    def test_names_match_agility(self):
        self.assertTrue(_names_match("Agility", "Tomb Raider: Agility Skill", PARENT))


class RatingProgressEnumTests(unittest.TestCase):
    def test_score_labels(self):
        from infinitebacklog_mcp.normalize import rating_label

        self.assertEqual(rating_label(10), "Masterpiece")
        self.assertEqual(rating_label(5), "Mediocre")
        self.assertEqual(rating_label(1), "Disaster")


    def test_status_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_status

        self.assertEqual(normalize_status("Played"), "played")
        self.assertEqual(normalize_status("No Status"), "noStatus")
        self.assertEqual(normalize_status("playing"), "playing")

    def test_completion_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_completion

        self.assertEqual(normalize_completion("Beaten"), "campaignCompleted")
        self.assertEqual(normalize_completion("campaignCompleted"), "campaignCompleted")
        self.assertEqual(normalize_completion("Not Started"), "notStarted")
        self.assertEqual(normalize_completion("Dropped"), "dropped")


class AcquisitionPlayRecordTests(unittest.TestCase):
    def test_acquisition_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_acquisition

        self.assertEqual(normalize_acquisition("Purchase"), "purchase")
        self.assertEqual(normalize_acquisition("Gifted"), "gift")
        self.assertEqual(normalize_acquisition("key bundle"), "keyBundle")
        self.assertEqual(normalize_acquisition("Free-to-play"), "freeToPlay")

    def test_digital_store_aliases(self):
        from infinitebacklog_mcp.normalize import normalize_digital_store

        self.assertEqual(normalize_digital_store("Steam"), "steam")
        self.assertEqual(normalize_digital_store("Epic Games"), "epicGameStore")
        self.assertEqual(normalize_digital_store("GOG"), "gog")

    def test_clear_fields_json_list(self):
        from infinitebacklog_mcp.normalize import parse_clear_fields

        self.assertEqual(parse_clear_fields('["source","amount"]'), ["source", "amount"])
        self.assertEqual(parse_clear_fields("notes,date"), ["notes", "date"])

    def test_play_record_types(self):
        from infinitebacklog_mcp.normalize import normalize_play_record_type

        self.assertEqual(normalize_play_record_type("Key-Value Pair"), "keyValue")
        self.assertEqual(normalize_play_record_type("checkbox"), "checkbox")
        self.assertEqual(normalize_play_record_type("table"), "table")

    def test_clear_fields_empty(self):
        from infinitebacklog_mcp.normalize import parse_clear_fields

        self.assertEqual(parse_clear_fields(""), [])

    def test_profile_scope_shape(self):
        from infinitebacklog_mcp.normalize import profile_scope

        out = profile_scope("global_category", "MCP probe")
        self.assertEqual(out["error"], "profile_scope")
        self.assertIn("profile", out["hint"].lower())
        self.assertEqual(out["detail"], "MCP probe")


    def test_slim_row_includes_acquisition(self):
        from infinitebacklog_mcp.normalize import slim_collection_row

        slim = slim_collection_row(
            {
                "id": 9866217,
                "acquisition": "purchase",
                "digital_store": "steam",
                "purchase_place_name": "MCP probe",
                "purchase_price": "1.00",
                "acquisition_notes": "MCP probe",
                "gameplay_stats_id": None,
            }
        )
        self.assertEqual(slim["acquisition"], "purchase")
        self.assertEqual(slim["purchase_place_name"], "MCP probe")
        self.assertEqual(slim["digital_store"], "steam")


class UserIdSearchTests(unittest.TestCase):
    def test_matches_username_not_first_row(self):
        from infinitebacklog_mcp.pages import user_id_from_search

        rows = [
            {"id": 1, "username": "someone_else"},
            {"id": 2002, "username": "Example_User"},
        ]
        self.assertEqual(user_id_from_search("example_user", rows), 2002)

    def test_no_match_returns_zero(self):
        from infinitebacklog_mcp.pages import user_id_from_search

        self.assertEqual(user_id_from_search("example_user", [{"id": 1, "username": "someone_else"}]), 0)
        self.assertEqual(user_id_from_search("example_user", None), 0)


class ConfirmGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_copy_requires_confirm(self):
        from infinitebacklog_mcp.tools.collection import delete_game_copy

        out = json.loads(await delete_game_copy("boxes-lost-fragments", "9866217", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_delete_copy_requires_collection_id(self):
        from infinitebacklog_mcp.tools.collection import delete_game_copy

        out = json.loads(await delete_game_copy("boxes-lost-fragments", "", confirm=True))
        self.assertEqual(out["error"], "collection_id_required")

    async def test_remove_play_record_requires_confirm(self):
        from infinitebacklog_mcp.tools.play_records import remove_play_record

        out = json.loads(await remove_play_record("boxes-lost-fragments", "MCP probe", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_delete_review_requires_confirm(self):
        from infinitebacklog_mcp.tools.reviews import delete_game_review

        out = json.loads(await delete_game_review("boxes-lost-fragments", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_delete_published_review_still_needs_confirm(self):
        from infinitebacklog_mcp.tools.reviews import delete_game_review

        out = json.loads(await delete_game_review("boxes-lost-fragments", confirm=False, published=True))
        self.assertEqual(out["error"], "confirm_required")

    async def test_remove_playthrough_requires_confirm(self):
        from infinitebacklog_mcp.tools.playthroughs import remove_playthrough

        out = json.loads(await remove_playthrough("hades--1", "Speedrun", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_remove_game_content_requires_confirm(self):
        from infinitebacklog_mcp.tools.related import remove_game_content

        out = json.loads(await remove_game_content("the-witcher-3-wild-hunt", "Hearts of Stone", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_delete_custom_tag_requires_confirm(self):
        from infinitebacklog_mcp.tools.tags import delete_custom_tag

        out = json.loads(await delete_custom_tag("VR", confirm=False))
        self.assertEqual(out["error"], "confirm_required")

    async def test_play_session_validates_before_browser(self):
        from infinitebacklog_mcp.tools.playthroughs import add_play_session

        out = json.loads(await add_play_session("hades--1", date="11/10/2026"))
        self.assertEqual(out["error"], "invalid_date")
        out = json.loads(await add_play_session("hades--1", date="2026-11-10", hours="25"))
        self.assertEqual(out["error"], "too_long")


if __name__ == "__main__":
    unittest.main()
