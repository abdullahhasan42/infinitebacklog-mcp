# Infinite Backlog v2.1.0 API notes

Mapped on 2026-11-11 from the site's own bundle and live calls on a test account. Paths are relative to `https://infinitebacklog.net/api`. Every call except `/startup` and public game data needs `Authorization: Bearer <keycloak token>`; the SPA mints it through `keycloak-js` (`/auth/realms/ib`, client `web-application`) and refreshes it before each call. Cookies alone return 401.

The server's allowlist lives in `src/infinitebacklog_mcp/security.py` (`API_RULES`). The server can also sign in without a browser; see [Sign-in (HTTP mode)](#sign-in-http-mode).

## Identity and reference data

| Call | Notes |
| --- | --- |
| `GET /users/me/complete` | Signed-in user: `id`, `username`, `currency`, `settings.preferences.review_language`. |
| `GET /startup` | `version`, `platforms[]` (`id`, `name`, `abbreviation`, `alternative_name`, `slug`), genres, modes. PC is `Windows PC` (id 6). |
| `GET /users?search=` | User search; pick the exact username, never the first row. |

## Games

| Call | Notes |
| --- | --- |
| `GET /games?query=&limit=&offset=` | Catalog search. `x-total-count` header has the total. |
| `GET /games/slug/{slug}?expand=full` | Returns a one-item list. `expand=full` adds playtime, developers, `rating_ib`, and `user_collection` / `user_rating` / `user_wishlist` for the signed-in user. |
| `GET /games/{id}/categories?category[]=0..14` | Related games. IGDB categories: 1 DLC, 2 expansion, 3 bundle, 4 standalone expansion, 5 mod, 6 episode, 7 season, 8 remake, 9 remaster, 13 pack, 14 update. |
| `GET /games/{id}/ratings` | Rating distribution. |
| `GET /user_collections/statistics?game_id=` | Owners per status/completion, wishlist count. |

## Collection copies

A copy is a `user_collections` row. Create and update go through the same call:

`POST /user_collections/bulk` with an array. A row without `id` is created; a row with `id` is updated. The SPA sends the full row it got from `GET`, with the edited fields changed.

New row (what the add dialog sends):

```json
{"game_id": 113112, "status": "unplayed", "completion": "notStarted", "platform_id": 169,
 "ownership": "owned", "playtime_type": "manual", "subscription": null, "physical": true,
 "tags": [], "bundled_games": [], "edition_id": null, "edition": null, "additions": []}
```

| Call | Notes |
| --- | --- |
| `GET /user_collections?user_id=&game_id=` | Your copies of one game. |
| `GET /user_collections?user_id=&status=&search=&limit=&offset=&sort_field=&sort_order=` | Collection list. |
| `DELETE /user_collections/{id}` | Delete one copy. |

Field values:

- `status`: `noStatus`, `unplayed`, `playing`, `played`
- `completion`: `noStatus`, `notStarted`, `unfinished`, `campaignCompleted` (Beaten), `completed`, `continuous`, `dropped`
- `ownership`: `owned`, `household`, `subscription`, `borrowed`, `rented`, `unlicensed`, `formerlyOwned`, `other`, `lentOut`
- `region`: `pal`, `ntsc-u`, `ntsc-j`, `ntsc-c`, `australia`, `brazil`, `asia`, `korea`, `other`
- `manual_progress`: 0-100; `playtime`: minutes; `completion_date` + `completion_date_type` (`day` / `month` / `year`)
- `playtime_type`: `manual`, `playthrough` or `synced`. The tools save a new `playtime` as `manual` unless you pass another type.
- `acquisition`: `purchase`, `subscription`, `gift`, `trade`, `keyBundle`, `promotionalCopy`, `reviewCopy`, `free`, `freeToPlay`
- `purchase_price`, `additional_cost`: integers in the minor unit of your currency (cents), except JPY, VND, KRW, CLP
- `purchase_place_id` / `purchase_place_name` (look up with `GET /purchase_places?search=`), `purchase_date`, `acquisition_notes`, `digital_store` (`steam`, `epicGameStore`, `gog`, `psn`, `xboxLive`, `nintendoEShop`, ...)
- `state`: `new` / `used`; `condition`: `cib`, `incomplete`, `loose`, `sealed`; `condition_game|box|manual`: `mint`, `good`, `acceptable`, `poor`, `missing`, `na`
- `additions`: DLC and packs on this copy, `{game_id, completion}`. DLC/expansions get `completion: "notStarted"`, packs/add-ons `null`.
- `tags`: `[{id, name, color, description}]` from the tag library.

## Ratings and reviews

| Call | Notes |
| --- | --- |
| `GET /ratings?user_id=&game_id=` | Your rating or empty. |
| `POST /ratings`, `PUT /ratings/{id}`, `DELETE /ratings/{id}` | Body: `game_id`, `score`, `gameplay`, `story`, `visual`, `sound`, `accessibility` (1-10 or null). UI labels: Audio = `sound`, Playability = `accessibility`. |
| `GET /users/{username}/reviews/{slug}` | Your review of a game (draft or published). |
| `POST /reviews/`, `PUT /reviews/{id}`, `DELETE /reviews/{id}` | Required: `game_id`, `platform_id`, `language`, `completion`, `mature_content`, `content` (HTML). Also `title` (5-100), `pros[]`, `cons[]`, `score`, sub-scores, `spoilers`, `published`, `post_feed`, `images[]`. Publishing needs 800+ text characters and a score. |

## Play records

One play records object per copy (it can be shared between copies).

| Call | Notes |
| --- | --- |
| `POST /user_collections/{cid}/gameplay_stats` | Create; returns `{id, collection_games, categories}`. The copy then has `gameplay_stats_id`. |
| `GET /user_collection_gameplay_stats/{id}` | Categories with `data` rows and nested `children`. |
| `POST /user_collection_gameplay_stats/{id}/categories` | New category. |
| `PUT /user_collection_gameplay_stats/{id}/categories/{catId}` | Full category including `data`; this is how rows are added, edited and removed. |
| `DELETE /user_collection_gameplay_stats/{id}/categories/{catId}` | Delete a category. |
| `DELETE /user_collection_gameplay_stats/{id}` | Delete the whole play records object. |
| `POST /user_collection_gameplay_stats/{id}/copy` | Body `{user_collection_id}`. Duplicates the play records to another copy of the same game. |
| `PATCH /user_collection_gameplay_stats/{id}` | Send the full object with `collection_games` set to the copies that share it. Add a copy ID to share; leave one out to stop sharing. |

New category: `{name, type, columns (1|2), bordered, description_available, date_available, data: [], order, icon: null, parent_id, icon_size: "small", dlc_game_id, bundled_game_id}`.

Row shapes by `type`:

- `keyValue`: `{order, name, value, icon}`
- `checkbox`: `{order, name, unlocked, earned_date, icon}`
- `progress`: `{order, name, description, progress_earned, progress_total, earned_date, icon}`
- `table`: `{order, values: [..]}`
- `text`: `{order, content}` (one row)

## Playthroughs and sessions

| Call | Notes |
| --- | --- |
| `GET /user_collections/{cid}/playthroughs` | A copy with none returns one unsaved default (no `id`). |
| `POST /user_collections/{cid}/playthroughs/init` | Saves that default. |
| `POST /user_collections/{cid}/playthroughs` | New: `{name, type, difficulty, notes, playtime_type, duration, bundle, collection_games: [cid], sessions: []}`. |
| `PUT /user_collection_playthroughs/{id}?user_collection_id={cid}` | Edit (body without `sessions`). |
| `DELETE /user_collection_playthroughs/{id}` | Delete with its sessions. |
| `POST /user_collection_playthroughs/{id}/sessions` | `{date, duration (minutes, max 1440), status, content, platform_id, friends, dlc, season, stream, update, post_feed, user_collection_playthrough_id}`. |
| `PUT /user_collection_playthroughs/{id}/sessions/{sid}?user_collection_id={cid}`, `DELETE .../sessions/{sid}` | Edit / delete a session. |
| `GET /user_collection_playthrough_sessions?user_id=` | Journal across games. |

Playthrough `type`: `firstPlaythrough`, `replay`, `speedrun`, `coop`, `competitive`, `continuous`, `streaming`, `achievements`, `challengeRun`. `playtime_type`: `session` or `playthrough`. With `playthrough`, the total is `duration` (minutes). With `session`, the total is the sum of the sessions plus `playtime_offset` (minutes), which is sent on the `PUT` above. Session `status`: `start`, `playing`, `campaignCompleted`, `completed`, `shelved`, `dropped`.

## Tags

| Call | Notes |
| --- | --- |
| `GET /user_collection_tags?user_id=` | Your tag library. |
| `POST /user_collection_tags` | `{name, description, color}`. Returns 403 `FORBIDDEN` (role) for non-supporter accounts. |
| `DELETE /user_collection_tags/{id}` | Removes it from every game. |

## Wishlist

| Call | Notes |
| --- | --- |
| `GET /user_wishlists?user_id=&game_id=` | Rows: `id`, `game`, `notes`, `preorder`, `favourite`, `platforms`, `tags`. `game_id` narrows to one game. The list tool sends `user_id`, `limit` and `offset`. |
| `POST /user_wishlists` | Body `{game_id}`. |
| `PUT /user_wishlists/{id}` | Full row with your changes (`notes`, `preorder`). |
| `DELETE /user_wishlists/game/{game_id}` | Remove the game from your wishlist. |

## Custom lists

| Call | Notes |
| --- | --- |
| `GET /lists?user_id=` | Your lists. Rows include `id`, `title`, `published`, `total_games`, `updated_at`. |
| `GET /lists/{id}` | One list: `title`, `description`, `published`, `ranked`, `games` (in order: `id`, `name`, `slug`) and `user`. |
| `POST /lists` | Create. Body below. |
| `PUT /lists/{id}` | Full object from `GET` with your changes. |
| `DELETE /lists/{id}` | Delete. |

Create body, as the site posts it for a personal list. `published` is `false` for a draft:

```json
{"title": "...", "description": "<p>...</p>", "games": [{"id": 1, "name": "...", "slug": "..."}],
 "display": "grid", "sorting": "list", "sorting_order": "asc", "type": "personal",
 "ranked": false, "published": false, "post_feed": false, "spoilers": false,
 "mature_content": false, "tags": [], "list_template_id": null, "banner": null}
```

## Playtime contributions

| Call | Notes |
| --- | --- |
| `GET /user_playtimes?user_id=` | Your submitted figures, newest first (`sort_field=updated_at`, `sort_order=desc`). Each row has its `game`. |
| `POST /user_playtimes` | Body `{game_id, campaign_completed, completed}`, times in minutes. A version or edition reports against its parent game. |
| `PUT /user_playtimes/{id}` | Body `{campaign_completed, completed}`. Used when the game already has a figure from you. |

The site only enables this when the copy's completion is Beaten or Completed. There is no delete endpoint: send a new `PUT` to change the figures.

## Achievements

| Call | Notes |
| --- | --- |
| `GET /accomplishment_games?game_id=&user_id=` | Sets per service with totals and your earned count. `service`: 1 Steam, 5 GOG, 12 PlayStation, 18 Xbox, 101 FFXIV, 102 RetroAchievements, 103 Battle.net. |
| `GET /user_{steam,xbox,gog,retro_achievement}_games/{external_id}/achievements?user_id=` | Achievement list for a set (works unsynced). |
| `GET /user_psn_games/{external_id}/trophies?user_id=` | PlayStation trophies. |
| `GET /user_accomplishment_games?user_id=` | Your synced achievement games. |

## Stats

| Call | Notes |
| --- | --- |
| `GET /users/{id}/statistics` | Activity, collection, contribution, social, achievements. |
| `GET /users/{id}/statistics/profile`, `/statistics/rating` | Profile summary, rating spread. |
| `GET /users/{id}/user_collection_statistic?year=&month=` | Yearly or monthly recap. |

## Sign-in (HTTP mode)

HTTP mode signs in without a browser, through the same Keycloak login the site uses. Realm: `https://infinitebacklog.net/auth/realms/ib`. Client: `web-application`. Nothing is written to disk. The password and tokens stay in memory.

1. `GET {realm}/protocol/openid-connect/auth` with `client_id=web-application`, `response_type=code`, `response_mode=query`, `scope=openid`, `redirect_uri=https://infinitebacklog.net/`, a random `state` and `nonce`, `code_challenge` (the S256 hash of a random `code_verifier`) and `code_challenge_method=S256`. The response is the login page.
2. `POST` the form's action URL with `username`, `password` and `credentialId` (empty). The `kc-form-login` form action must stay under `/auth/realms/ib/login-actions/`. A wrong login doesn't redirect; the page shows an error message instead.
3. The redirect to `https://infinitebacklog.net/` carries `code` and `state` in its query string. Check that `state` matches the one you sent.
4. `POST {realm}/protocol/openid-connect/token` with `grant_type=authorization_code`, `client_id`, `code`, `redirect_uri` and `code_verifier`. The response has `access_token`, `refresh_token` and `expires_in`.
5. Before the access token expires, `POST` the same token URL with `grant_type=refresh_token`, `client_id` and `refresh_token`. Send API calls with `Authorization: Bearer <access_token>`.

If the login page is not the plain form, or Keycloak asks for a captcha or 2FA, the sign-in stops with `browser_sign_in_required`. The device code grant is disabled for this client, so it can't be used for sign-in.
