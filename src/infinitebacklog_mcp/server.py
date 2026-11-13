"""Infinite Backlog Hybrid MCP Server entry point."""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .config import logger
from .tools import register_all

mcp = MCPServer(
    name="infinitebacklog",
    version="2.1.0",
    instructions=(
        "Tools for Infinite Backlog (https://infinitebacklog.net/), built for site v2.1.0. "
        "They call the site's JSON API from inside a signed-in browser tab, the same calls the "
        "website makes. Before any browser opens, the user picks which one: the server asks "
        "through the client, or returns browser_choice_required; then relay the options to the "
        "user and call choose_browser with THEIR pick. Never choose a browser for the user. "
        "Launched browsers use this server's own private profile; no cookie file is read. "
        "Sign in once: login (uses IB_USERNAME/IB_PASSWORD from .env) or open_site and sign in "
        "in the window. The window stays visible because the site renders blank headless. "
        "Find games with search_games and pass the slug to the other tools (Hades 2020 is hades--1). "
        "A game can have several copies (one per platform); when it does, pass collection_id "
        "(list_collection_game_options shows them). "
        "Collection: add_game_to_collection, add_game_platform_copy, set_game_progress, "
        "set_game_details, set_game_acquisition, delete_game_copy (confirm=true). "
        "DLC/packs: list_related_content, list_collection_content_menus, add_game_content, "
        "remove_game_content. Ratings are per game: set_game_rating. Reviews: add_game_review "
        "(draft unless publish=true; publish needs 800+ chars and a score), delete_game_review. "
        "Play Records are per copy: list_play_records, set_play_record_category "
        "(keyValue/checkbox/progress/table/text), set_play_record, remove_play_record. "
        "Playthroughs and sessions: list_playthroughs, set_playthrough, remove_playthrough, "
        "add_play_session, remove_play_session, get_play_journal. Tags: list_custom_tags, "
        "set_game_tags, delete_custom_tag (custom tags need an IB supporter role; the API "
        "answers feature_locked otherwise). Stats and achievements: get_game, get_game_stats, "
        "list_achievements, get_user_stats, list_collection. "
        "Wishlist: list_wishlist, add_to_wishlist, remove_from_wishlist. Custom lists: list_my_lists, get_list, create_list, update_list, delete_list (drafts unless publish=true). Playtime contributions: list_playtime_contributions, submit_playtime (needs a Beaten/Completed copy and confirm=true). Play records sharing: copy_play_records, share_play_records. "
        "Deletes need confirm=true. Never change profile settings. API calls outside this "
        "server's allowlist are refused. Sign-in modes (the user picks one first): a browser "
        "tab used only to sign in and hold the token, or no browser at all (HTTP mode, using "
        "the .env account). Everything goes through the API; there are no page-scraping tools. "
        "Do not ask anyone to copy, export, or paste session cookies."
    ),
)


register_all(mcp)


def main() -> None:
    logger.info("Starting Infinite Backlog MCP server")
    mcp.run()


if __name__ == "__main__":
    main()
