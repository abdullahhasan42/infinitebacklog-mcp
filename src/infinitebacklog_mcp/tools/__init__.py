"""Register all Infinite Backlog MCP tools on an MCPServer instance."""
from __future__ import annotations

from . import auth, collection, games, navigation
from . import play_records, playthroughs, playtimes, ratings, related, reviews, stats, tags
from . import lists, wishlist


def register_all(mcp) -> None:
    navigation.register(mcp)
    auth.register(mcp)
    games.register(mcp)
    collection.register(mcp)
    related.register(mcp)
    ratings.register(mcp)
    reviews.register(mcp)
    play_records.register(mcp)
    playthroughs.register(mcp)
    tags.register(mcp)
    wishlist.register(mcp)
    lists.register(mcp)
    playtimes.register(mcp)
    stats.register(mcp)
