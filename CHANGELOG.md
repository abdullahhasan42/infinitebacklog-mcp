# Changelog

## 2.1.0 (2026-11-12)

### Added

- HTTP sign-in mode (`http`). No browser is needed. The server signs in with `IB_USERNAME` and `IB_PASSWORD` from `.env` through Infinite Backlog's own login form over HTTPS (authorization code with PKCE). It solves no captchas. If the login asks for one, it stops with `browser_sign_in_required`; use a browser mode then.

### Removed

- The eight page tools: `get_page_text`, `get_page_html`, `get_links`, `screenshot`, `click`, `fill`, `evaluate_js` and `run_browser_use_task`. The code is kept in the git tag `v2.0.0-with-dom-tools`.
- The optional browser-use `[agent]` extra, the `IB_ALLOW_EVAL_JS` setting and the LLM API key variables.

Total: 50 tools.

### Changed

- API only. Every tool reads and writes through Infinite Backlog's JSON API. A browser is only used, if you pick a browser mode, as the place where you sign in and the short-lived token comes from.
- Network hiccups are retried once for repeatable calls (reads, full updates, deletes) and reported as `network_error` instead of crashing the server. Creates are never resent, so nothing is added twice.
- Oversized replies stay valid JSON.

## 2.0.0 (2026-11-12)

Rebuilt for Infinite Backlog v2.1.0.

### Changed

- Tools call the site's own JSON API from inside a signed-in browser tab instead of scraping pages.
- Every call is checked against an allowlist before it runs.
- Nothing opens a browser until you pick one, through the MCP prompt or `choose_browser`.
- Each launched browser uses its own private profile.
- Browser detection is generic: Chromium-based browsers are found by their resource files, with no brand names.
- The browser window stays visible, because the site renders blank in headless mode.

### Added

- Wishlist.
- Custom lists. Lists stay drafts unless `publish=true`.
- Playtime contributions (`submit_playtime`, needs `confirm=true`). There is no delete; submitting again replaces your figures.
- Playthroughs and play sessions.
- Play records with five category types (`keyValue`, `checkbox`, `progress`, `table`, `text`), and copying or sharing them between copies of a game.
- Custom tags.
- Achievement lists.
- Game and profile stats.
- Collection details: ownership, region, edition and lending.
- `choose_browser`.

Total: 58 tools.

### Removed

- The v1 page scraping.
- The browser-specific relaunch and debug-port bridge code.

### Security

- HTML passed to reviews and play records is checked and escaped if unsafe.
- Delete actions need `confirm=true`.
- No paths, process lists or tokens are reported.

## 1.x

The original page-scraping version for Infinite Backlog v1.
