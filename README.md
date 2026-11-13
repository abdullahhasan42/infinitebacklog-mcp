![Infinite Backlog MCP](docs/assets/readme-header.svg)

# Infinite Backlog MCP

An [MCP](https://modelcontextprotocol.io/) server that lets an AI assistant manage your [Infinite Backlog](https://infinitebacklog.net/) account.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)
![MCP](https://img.shields.io/badge/protocol-MCP-555555.svg)

## Goals

- Let your assistant read and update your Infinite Backlog collection without you clicking through the site.
- Use the same calls the website makes, so the results match what you see in your account.
- Stay safe by default: nothing deletes, publishes or posts unless you ask for it.

Built for Infinite Backlog **v2.1.0**. This is an unofficial project, not affiliated with Infinite Backlog. It uses the site's private API, which can change without notice. Check Infinite Backlog's terms before heavy use.

## What it can do

- **Catalog:** search games, game info, community stats, DLC and editions, achievements and trophies.
- **Collection:** add games and platform copies, set status, progress, playtime, notes, details and acquisition.
- **Ratings and reviews:** overall and sub-ratings, reviews saved as drafts or published.
- **Play records:** your own notes and checklists per copy (key/values, checklists, progress bars, tables, text).
- **Playthroughs and sessions:** log playthroughs and play sessions, read your play journal.
- **Tags:** custom tags on your copies.
- **Wishlist and lists:** manage your wishlist and your custom lists.
- **Playtime:** submit time to beat and time to complete, and read what you submitted.
- **Stats:** your collection, activity and yearly stats.

## What it can't do

- Read or click through web pages. Every tool uses the site's API.
- Change your profile, settings, widgets, friends or feed.
- Post to the community feed.
- Publish a list or submit playtimes unless you ask for it.
- Sign in past a captcha or second factor. You finish those by hand (browser mode) or switch modes.
- Call any API endpoint that isn't on its allowlist, or open any site other than infinitebacklog.net.

## Installation

1. Install Python 3.11 or newer.
2. Set up the server:

   ```bash
   cd infinitebacklog-mcp
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   python -m playwright install chromium   # only for the bundled browser option
   ```

3. Copy `.env.example` to `.env` and fill in `IB_USERNAME` (username or email) and `IB_PASSWORD`. The `login` tool uses them. HTTP mode needs them. In a browser mode you can sign in by hand instead. Never commit `.env`.
4. Add the server to your MCP client:

   ```json
   {
     "mcpServers": {
       "infinitebacklog": {
         "command": "C:/path/to/infinitebacklog-mcp/.venv/Scripts/python.exe",
         "args": ["-m", "infinitebacklog_mcp.server"],
         "cwd": "C:/path/to/infinitebacklog-mcp"
       }
     }
   }
   ```

   After `pip install -e .` you can use `"command": "infinitebacklog-mcp"` instead. Logs go to stderr.

5. Start your MCP client. The first tool call asks which sign-in mode to use. You can also call `choose_browser` yourself.
6. Sign in once. In a browser mode, the server signs in with `.env` when the browser first opens, or you can call `login`, or sign in by hand in the window. In HTTP mode, the server signs in with `.env` on the first call. Nothing opens.
7. Try `search_games` and `list_collection`.

## Sign-in modes

Nothing signs in or opens until you choose a mode. The choice lasts until the server stops and is never written to disk. To skip the question, set `IB_BROWSER`.

**Browser modes.** A window opens. Sign in there by hand, or let the server fill in `IB_USERNAME` and `IB_PASSWORD`. The session is saved in the server's profile folder and reused. The window stays visible, because Infinite Backlog renders blank in headless browsers. The options:

- a Chromium-based browser that is your system default or currently open, started with the server's own private profile
- Playwright's bundled Chromium, also with a private profile
- an already-open browser with a local debug port (`--remote-debugging-port=9222`, or `IB_CDP_URL`). This uses that browser's real profile and opens one new tab. You opt in to this one.
- any other Chromium-based browser you point to by path

Firefox and Safari can't be driven this way. Pick the bundled Chromium if one of them is your default. The server never reads cookies or profile data from your everyday browser.

**HTTP mode.** No browser. The server signs in through Infinite Backlog's own login form over HTTPS, with the standard authorization code and PKCE flow, then refreshes the token as needed. It identifies itself as `infinitebacklog-mcp`. It solves no captchas. If the login asks for a captcha or 2FA, it stops with `browser_sign_in_required`, and you switch to a browser mode. In HTTP mode, `open_site` and `current_url` don't apply.

| | Browser mode | HTTP mode |
| --- | --- | --- |
| Needs a browser | Yes | No |
| Sign in by hand | Yes | No |
| Needs `IB_USERNAME` and `IB_PASSWORD` in `.env` | Optional | Yes |
| Captcha or 2FA | Yes, by hand in the window | No, the server stops and asks you to switch |

Neither mode writes tokens to disk. The password is never logged or returned.

## Supported tools

Games are identified by their slug from `search_games`. You can own a game more than once, one copy per platform. Progress, acquisition, DLC, tags, play records and playthroughs belong to a copy. Ratings and reviews belong to the game. When a game has several copies, pass `collection_id` (shown by `list_collection_game_options`).

Anything that deletes needs `confirm=true`.

### Catalog and game info

| Tool | What it does |
| --- | --- |
| `search_games` | Search the catalog. Returns name, slug, year, type. |
| `get_game` | Summary, platforms, developers, scores, average playtimes, and your status for that game. |
| `list_related_content` | DLC, expansions, packs and add-ons, editions, bundles, remakes. |
| `get_game_stats` | Community numbers: owners per status and completion, wishlists, rating distribution. |
| `list_achievements` | Achievement and trophy sets (Steam, PlayStation, Xbox, GOG, RetroAchievements) with your progress. `include_list=true` lists every achievement. |

### Your collection

| Tool | What it does |
| --- | --- |
| `list_collection` | Your games, filterable by status or title. |
| `list_collection_game_options` | Everything about your copies of one game. |
| `add_game_to_collection` | Add a game on a platform, physical or digital, with a starting status. |
| `add_game_platform_copy` | Add another copy on a different platform. |
| `set_game_progress` | Status, completion, progress bar (0-100), notes, playtime and playtime type, times finished, completion date. |
| `set_game_details` | Platform, ownership, digital or physical, region, edition, lent to or borrowed from. |
| `set_game_acquisition` | How and where you got it, date, price, notes, digital store, and condition for physical copies. |
| `delete_game_copy` | Remove one copy. |

### DLC and add-ons

| Tool | What it does |
| --- | --- |
| `list_collection_content_menus` | DLC and packs attached to a copy, and the ones you can still add. |
| `add_game_content` | Attach DLC, expansions, packs or add-ons by name (or IGDB id). Already-owned items are skipped. |
| `remove_game_content` | Detach them again. |

### Ratings and reviews

| Tool | What it does |
| --- | --- |
| `set_game_rating` | Overall 1-10, plus Gameplay, Story, Visual, Audio and Playability. `clear=true` removes it. |
| `add_game_review` | Write or edit a review. A draft unless `publish=true` (needs 800+ characters and a score). |
| `delete_game_review` | Delete it. A published review also needs `published=true`. |

### Play records

Play records are your own notes and checklists for a copy, grouped in categories. Five types:

- `keyValue`: name and value ("Final boss" / "Beaten")
- `checkbox`: a checklist, with optional earned dates (good for tracking achievements by hand)
- `progress`: earned / total, with an optional description
- `table`: rows of columns
- `text`: one free-text note

| Tool | What it does |
| --- | --- |
| `list_play_records` | All categories and rows, numbered from 1. |
| `set_play_record_category` | Add, nest, rename or restyle a category. |
| `set_play_record` | Add a row, or update one by number or name. |
| `remove_play_record` | Remove a row, or a whole category. |
| `copy_play_records` | Copy one copy's play records to another copy of the same game. The target must have none yet. |
| `share_play_records` | Share with another copy of the same game (`share=true`), or stop sharing (`share=false`). |

### Playthroughs and sessions

| Tool | What it does |
| --- | --- |
| `list_playthroughs` | Playthroughs of a copy with their sessions. |
| `set_playthrough` | Create or edit one: name, type, difficulty, notes, playtime. `extra_hours` and `extra_minutes` add time on top. |
| `remove_playthrough` | Delete a playthrough and its sessions. |
| `add_play_session` | Log a session: date, time played, status, notes. Pass `session_id` to edit one. |
| `remove_play_session` | Delete a session. |
| `get_play_journal` | Your latest sessions across all games. |

### Tags and stats

| Tool | What it does |
| --- | --- |
| `list_custom_tags` | Your custom tags. |
| `set_game_tags` | Add or remove tags on a copy. Creating new tags needs an Infinite Backlog supporter account (otherwise `feature_locked`). |
| `delete_custom_tag` | Remove a tag from your library. |
| `get_user_stats` | Collection, activity, achievement and rating stats, plus a yearly or monthly recap. |

### Wishlist

| Tool | What it does |
| --- | --- |
| `list_wishlist` | Your wishlist, with notes, pre-order and favourite flags. |
| `add_to_wishlist` | Add a game, or update one already on the list (`notes`, `preorder`). |
| `remove_from_wishlist` | Remove a game. Needs `confirm=true`. |

### Custom lists

Lists are public once published, so they stay drafts unless you pass `publish=true`. Only your own lists can be changed or deleted.

| Tool | What it does |
| --- | --- |
| `list_my_lists` | Your lists: title, published flag, number of games, last update. |
| `get_list` | One list with its games in order. |
| `create_list` | New list from comma-separated game slugs. |
| `update_list` | Change `title`, `description`, `add_games`, `remove_games`, `ranked` or `publish`. |
| `delete_list` | Delete one of your lists. Needs `confirm=true`. |

### Playtime contributions

Submitted times go to Infinite Backlog's public playtime data. There is no delete. Submitting again replaces your figures.

| Tool | What it does |
| --- | --- |
| `list_playtime_contributions` | The playtime figures you have submitted, newest first. |
| `submit_playtime` | Submit time to beat and time to complete. Needs a copy marked Beaten or Completed, and `confirm=true`. |

### Session

| Tool | What it does |
| --- | --- |
| `choose_browser` | List the sign-in options, or record the one you picked (including HTTP mode). |
| `login` | Sign in with `.env` credentials. Works in browser modes and HTTP mode. |
| `open_site`, `current_url`, `close_browser` | Browser modes only. Open a page in the server's window, show where it is, close it. |

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `IB_USERNAME`, `IB_PASSWORD` | empty | Sign-in for `login` and HTTP mode. Keep them out of git. |
| `IB_BROWSER` | empty (ask) | Pre-approve a sign-in mode: `bundled`, `default`, `attach` or `http`. |
| `IB_BROWSER_PATH` | empty | Pre-approve a specific Chromium-based browser by path. |
| `IB_CDP_URL` | `http://127.0.0.1:9222` | Local debug endpoint for the attach option. Only localhost is accepted. |
| `IB_HEADLESS` | `false` | Leave it off: the site renders blank headless. Browser modes only. |
| `IB_VIEWPORT_WIDTH`, `IB_VIEWPORT_HEIGHT` | 1280 x 800 | Window size. Browser modes only. |
| `IB_CHROMIUM_NO_SANDBOX` | `false` | Containers only. |

## Supported Platforms

Windows only for now. Other systems are untested. The code is written for them, so reports are welcome.

## More

- [docs/api-v2.md](docs/api-v2.md): the endpoints and payloads this server uses. If Infinite Backlog changes its API, start there.
- [AGENTS.md](AGENTS.md): notes for assistants calling the tools.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release.

## License

MIT. See [LICENSE](LICENSE).
