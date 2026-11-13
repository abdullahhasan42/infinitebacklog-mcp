# Infinite Backlog MCP: notes for assistants

This is for assistants calling the `infinitebacklog` tools. People installing the server should read [README.md](README.md). Never commit cookies, tokens, API keys or `.env`.

## How the server works

- It is API-only. Every tool calls Infinite Backlog's JSON API. There are no page-reading or page-clicking tools.
- A browser is optional. In a browser mode it is only the place where the person signs in and the short-lived token comes from. HTTP mode has no browser.
- **Sign-in mode belongs to the user.** Nothing signs in or opens until they pick a mode. If a tool returns `browser_choice_required`, show the user the `choices` (labels as given) and call `choose_browser` with the id they pick. Never pick for them, and never pick `attach` unless they asked for it: it works inside their real browser profile.
- Launched browsers use a private profile under `.playwright/`; the user's everyday profile isn't read.
- Built for site v2.1.0. API shapes are in [docs/api-v2.md](docs/api-v2.md).
- Only allowlisted endpoints can be called (`security.API_RULES`). Profile, settings, feed, friends and bulk-delete endpoints are not on it.
- In a browser mode the window is visible by default. The site renders blank headless, so don't pass `headless=true`.
- Tool calls run one at a time behind a lock.

## Sign-in modes

- **Browser modes:** a browser window opens. The person signs in there by hand, or the server fills in `IB_USERNAME` / `IB_PASSWORD` from `.env`. `open_site` and `current_url` work.
- **HTTP mode** (`http`): no browser. The server signs in with `IB_USERNAME` / `IB_PASSWORD` from `.env` over HTTPS. `open_site` returns `not_in_http_mode`, and `current_url` reports `mode=http (no browser)`.
- If HTTP mode hits a captcha or second factor, it stops with `browser_sign_in_required`. Tell the person, and ask them to switch to a browser mode and sign in by hand.

## Sign in

- If any tool returns `not_logged_in`: call `login` (uses `IB_USERNAME` / `IB_PASSWORD` from `.env`). In a browser mode, you can also call `open_site` and let the person sign in in the window. In HTTP mode, `open_site` is not available: check the `.env` values or ask the person to switch modes.
- If a captcha or second factor appears in a browser mode, stop and ask the person to finish in the window.
- If HTTP mode returns `browser_sign_in_required`, stop and ask the person to switch to a browser mode.
- Never ask anyone to copy, export or paste cookies or tokens.

## Picking a tool

| Goal | Tool |
| --- | --- |
| List or change the sign-in mode (user's pick only) | `choose_browser` |
| Open a page or show the current URL (browser modes only) | `open_site`, `current_url` |
| End the session (closes this server's window, or forgets the HTTP sign-in) | `close_browser` |
| Remove one copy from the collection (`confirm=true`) | `delete_game_copy` |
| Find a game, get its slug | `search_games` |
| Game info, community stats | `get_game`, `get_game_stats` |
| DLC / packs / editions of a game | `list_related_content` |
| Achievements and trophies | `list_achievements` |
| My collection | `list_collection` |
| Everything about my copies of one game | `list_collection_game_options` |
| Add a game / another platform copy | `add_game_to_collection`, `add_game_platform_copy` |
| Status, completion, progress bar, notes, playtime, finish date | `set_game_progress` |
| Platform, ownership, digital/physical, region, edition, lending | `set_game_details` |
| Purchase info and condition | `set_game_acquisition` |
| Attach / detach DLC and packs | `list_collection_content_menus`, `add_game_content`, `remove_game_content` |
| Rating and sub-ratings | `set_game_rating` |
| Review | `add_game_review`, `delete_game_review` |
| Play records (key/values, checklists, progress, tables, notes) | `list_play_records`, `set_play_record_category`, `set_play_record`, `remove_play_record` |
| Copy or share play records between copies of one game | `copy_play_records`, `share_play_records` |
| Playthroughs and play sessions | `list_playthroughs`, `set_playthrough`, `remove_playthrough`, `add_play_session`, `remove_play_session`, `get_play_journal` |
| Custom tags | `list_custom_tags`, `set_game_tags`, `delete_custom_tag` |
| Wishlist | `list_wishlist`, `add_to_wishlist`, `remove_from_wishlist` |
| Custom lists | `list_my_lists`, `get_list`, `create_list`, `update_list`, `delete_list` |
| Playtime contributions (time to beat, time to complete) | `list_playtime_contributions`, `submit_playtime` |
| Profile and yearly stats | `get_user_stats` |

There is no tool for reading or clicking through a web page. If no tool covers the task, say so to the person.

## Data model

- **Slugs** come from `search_games`. Same-name games get suffixes: Hades (1995) is `hades`, Hades (2020) is `hades--1`.
- **Copies.** A game can be owned on several platforms; each copy has its own `collection_id`. Progress, details, acquisition, DLC, tags, play records and playthroughs are per copy. When a game has more than one copy, tools answer `collection_id_required` with the list; ask which one or pick from context.
- **Ratings and reviews** are per game, not per copy.
- **DLC and packs** are `additions` on the parent copy. They are not separate collection rows, so never add a DLC with `add_game_to_collection`. Search `list_related_content` (all groups) before saying something doesn't exist; skins and cosmetic items are usually packs.
- **Editions** are set on a copy with `set_game_details edition_slug=...`; don't add an edition as its own game.
- **Prices** are passed as normal amounts (9.99); the server converts to IB's minor units.
- **Achievements** come from linked store accounts and are read-only here. To track them by hand, make a `checkbox` play records category.
- **Custom tags** need an IB supporter account to create. `feature_locked` means the account can't; report it, don't retry.

## Rules

- Change only what was asked. Don't touch status, platform, ownership or acquisition as a side effect.
- Anything that deletes (copies, DLC, reviews, play records categories, playthroughs, sessions, tags, wishlist entries, lists) needs `confirm=true`. Only pass it when the person asked for that deletion. A published review also needs `published=true`.
- Don't publish a review unless the person says to publish; drafts are the default.
- Never publish a list or submit playtimes unless the person explicitly asked. Both are public, and playtimes can't be deleted.
- Never post to the feed, change profile or settings, or touch other users' content.
- Be gentle with request volume; batch reads where a tool already returns everything.
