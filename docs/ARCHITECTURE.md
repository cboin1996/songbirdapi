# songbirdapi — architecture

## Request lifecycle

```
┌─────────────┐
│   client    │  (songbirdweb, songbirdcli, share-link visitor)
└──────┬──────┘
       │ HTTP + httpOnly cookies
       ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI app (songbirdapi/server.py)                         │
│                                                             │
│  ┌────────────────────┐  CORSMiddleware (allow_credentials) │
│  │ middleware stack   │                                     │
│  └─────────┬──────────┘                                     │
│            ▼                                                │
│  ┌────────────────────┐  routes mounted under /v1           │
│  │ APIRouter (prefix) │  (auth, songs, library, download,   │
│  │   per feature      │   edit, import, playlists, share,   │
│  │                    │   admin, offline, player, props,    │
│  │                    │   version)                          │
│  └─────────┬──────────┘                                     │
│            │                                                │
│            ▼                                                │
│  ┌────────────────────┐  Depends(get_current_user)          │
│  │  dependencies.py   │  Depends(require_admin)             │
│  │                    │  Depends(get_db) → AsyncSession     │
│  └─────────┬──────────┘                                     │
│            ▼                                                │
│  ┌────────────────────┐  reusable async DB helpers          │
│  │      crud.py       │  (get_song, search_songs, etc.)     │
│  └─────────┬──────────┘                                     │
│            ▼                                                │
│  ┌────────────────────┐  asyncpg pool                       │
│  │   database.py      │  init_engine / get_db generator     │
│  │  (engine + factory)│  Base.metadata.create_all on boot   │
│  └─────────┬──────────┘                                     │
│            ▼                                                │
│        PostgreSQL                                           │
└─────────────────────────────────────────────────────────────┘
```

Unhandled exceptions are caught by the `unhandled_exception_handler` registered in `server.py` — the traceback and request metadata are inserted into `error_logs` (best-effort) and a `500 Internal server error` response is returned.

## Module map

| Path | Responsibility |
|---|---|
| `songbirdapi/server.py` | FastAPI app, CORS, lifespan (init_engine + create_schema + seed_admin), router mounting under `/v1`, global exception handler |
| `songbirdapi/settings.py` | `SongbirdServerConfig` (pydantic-settings) — reads `<ENV>.env` |
| `songbirdapi/dependencies.py` | `get_current_auth` / `get_current_user` (decode JWT cookie, check the session is live), `require_admin`, `load_settings`, `process_song_url` |
| `songbirdapi/security.py` | Password hashing (bcrypt), `create_access_token` (15 min), `make_refresh_jwt`, `utcnow` (the app clock), `decode_token` |
| `songbirdapi/sessions.py` | `decide_refresh`: the pure refresh-token rules (see Auth model) |
| `songbirdapi/database.py` | Async engine + sessionmaker, `get_db` dependency, `seed_admin`, `dispose_engine` |
| `songbirdapi/models.py` | SQLAlchemy declarative models (single `Base`) |
| `songbirdapi/crud.py` | Reusable query/mutation helpers per entity |
| `songbirdapi/editor.py` | ffmpeg pipeline — trims, fades, cuts, speed (atempo), `dynaudnorm`, `volume` filter |
| `songbirdapi/artwork.py` | iTunes artwork download + Pillow resize to thumb (200px) and full (600px) JPEGs |
| `songbirdapi/dbclient.py` | Legacy DB helper used by older paths (kept for compat) |
| `songbirdapi/routers/` | One file per feature; see [`API.md`](API.md) |
| `migrations/` | Alembic env + versioned scripts |
| `scripts/` | One-shot dev tooling (`seed_dev.py`, etc.) |
| `tests/unit/` | No DB required |
| `tests/integration/` | Spin up Postgres via `ENV=dev` |

### Routers (per-feature, all mounted under `/v1`)

| File | Prefix | Purpose |
|---|---|---|
| `auth.py` | `/auth` | Login, logout, refresh, register (admin), `me`, change password |
| `admin.py` | `/admin` | User CRUD, system stats, edit-job inspector, error log viewer |
| `library.py` | `/library` | User's saved songs, eligibility, publish-to-community |
| `offline.py` | `/library/offline` | Per-user offline-marked song IDs (cross-device hint) |
| `songs.py` | `/songs` | List, search, explore stats, play recording, artwork serving |
| `properties.py` | `/properties` | iTunes lookup, song property CRUD, eligibility check |
| `downloads.py` | `/download` | yt-dlp downloads + ranged file streaming + delete |
| `edit.py` | `/edit` | Async edit jobs + per-song drafts |
| `imports.py` | `/import` | Multipart MP3/M4A upload jobs (semaphore-bounded) |
| `playlists.py` | `/playlists` | User playlists + ordered song membership |
| `player.py` | `/player` | Per-user persisted queue, shuffle/repeat, current uuid |
| `share.py` | `/share` | Time-limited unauthenticated share tokens |
| `version.py` | (none) | `GET /version` |

## Background tasks

`BackgroundTasks` is used for any operation that exceeds typical request budgets:

- **Imports** (`routers/imports.py`): `_import_semaphore = asyncio.Semaphore(5)` caps concurrent file processing. The HTTP `POST /import` returns `202 Accepted` with the new job IDs immediately; processing happens after the response is flushed.
- **Edits** (`routers/edit.py`): `POST /edit/songs/{id}` enqueues an `EditJob` (`pending → processing → done | failed | duplicate`) and runs `editor.apply_edits` in the background. Clients poll `GET /edit/jobs/{job_id}`.
- **Artwork fetch**: triggered by `PUT /properties` after an iTunes lookup — pulls 600×600 from `**.mzstatic.com` and resizes via Pillow.

The semaphore lives in process memory; multiple workers (e.g. multiple uvicorn replicas) each get their own. Today the API runs as a single uvicorn process.

## Auth model

| Token | Lifetime | Cookie | Claims |
|---|---|---|---|
| Access | 15 min | `access_token` (httpOnly, `Secure`, samesite=lax) | `sub`, `role`, `sid`, `type=access` |
| Refresh | up to 90 days from login | `refresh_token` (httpOnly, `Secure`, samesite=lax) | `sub`, `sid`, `jti`, `type=refresh` |

A login is a **session** (`auth_sessions` row, id = `sid`). The session slides: it dies after 30 days without a refresh, or 90 days after login regardless. Both limits are settings (`session_idle_days`, `session_absolute_days`). A user holds at most `session_max_per_user` (10) live sessions: a login beyond that revokes the least recently used. `Secure` on the cookies is the `cookie_secure` setting (on by default, off for plain-HTTP local dev).

- `POST /v1/auth/login` validates credentials with bcrypt, prunes the user's long-dead sessions, creates the session, and writes both cookies. The refresh cookie's `Max-Age` is the time left to the 90-day cap.
- `Depends(get_current_user)` decodes the `access_token` cookie, asserts `type=access`, and loads the user and its session in one query. 401 if the token has no `sid`, the session is missing, revoked or past the cap, or the user is inactive. A revoked session therefore stops working on the next request.
- `POST /v1/auth/logout` revokes the session named by the refresh cookie (or, with no refresh cookie, by an access cookie that expired under 24 h ago), deletes both cookies, and always answers 200.
- Disabling a user (`PATCH /v1/admin/users/{id}`) revokes all their sessions. At startup the API deletes dead sessions of every user.
- `PATCH /v1/auth/password` revokes every session of the user, the caller's included, and starts a new one for the caller (a thief who copied this device's cookies shares its session).
- `Depends(require_admin)` chains `get_current_user` and asserts `role=admin`.
- `POST /v1/auth/register` is gated behind `require_admin` — there is no public sign-up.

### Refresh rules (`sessions.decide_refresh`)

A refresh rotates the refresh token once it is older than 60 s: the session row keeps the current `jti` and the one before it (`prev_jti`), and the route locks the row (`SELECT … FOR UPDATE`) so concurrent refreshes line up. Judged in order, for the presented `jti`:

| Presented | Condition | Outcome |
|---|---|---|
| any | session revoked, idle over 30 d, or past the 90 d cap | 401 |
| current | rotated within the last 60 s | **hold**: same token back, no rotation (back-to-back refreshes from a page load and a first play) |
| current | rotated longer ago | **rotate**: new token |
| previous | within 60 s of the rotation | **replay**: current token back (two tabs, a quick retry) |
| previous | longer ago | **branch**: new token; the unused one is dead (a response lost in a dead zone) |
| older | — | **reuse**: the session is revoked and committed, then 401 |

`refresh_reuse_detection=false` turns *reuse* into *branch* and logs it; use it only if false logouts show up.

The browser keeps the cookies httpOnly so JS can't read them. `songbirdweb`'s middleware refreshes server-side on a page navigation once the access token has expired and hands the API's `Set-Cookie` lines to the browser unchanged; `app/lib/data.ts` does the same from the client.

## Queue sources

When a user plays music from a context (songs tab, artist page, explore, playlist), the client records the source via `queue_sources` — an array of `QueueSource` objects:

```python
class QueueSource(BaseModel):
    label: str      # "All Songs", "Artist: John Doe", etc.
    href: str       # "/library?view=songs", "/library?view=artists&artist=John+Doe"
    id: str | None  # playlist UUID if applicable; None for generated contexts
```

On every `PUT /v1/player/state`, the client includes the current `queue_sources`. On `GET /v1/player/state`, the server returns them so the player UI can display "Now playing from [label]" and reconstruct the original link.

This replaces the localStorage-only `playerSources` pattern — queue sources are now server-of-truth.

## Postgres schema

All tables live in the `public` schema and are managed by Alembic. The schema is also created from models on first boot (`Base.metadata.create_all` in the lifespan handler) so a fresh DB works out of the box.

| Table | Key fields | Notes |
|---|---|---|
| `auth_sessions` | `id` PK (= `sid`), `user_id` FK (cascade), `jti`, `prev_jti`, `created_at`, `last_used_at`, `rotated_at`, `revoked_at`, `revoke_reason`, `user_agent` | one row per login; timestamps written by the app clock |
| `users` | `id` PK, `username` U, `email` U, `role` enum(`admin`/`user`), `is_active` | bcrypt `hashed_password` |
| `songs` | `uuid` PK, `url`, `file_path`, `properties` JSONB, `artwork_thumb`, `artwork_full`, `parent_song_id` FK, `root_song_id` FK, `owner_id`, `source` | GIN index on `properties`; `parent_song_id` chains edit children |
| `user_songs` | (`user_id`, `song_id`) PK | per-user library; tracks `last_position`, `last_played_at` |
| `song_plays` | `id` PK, `song_id` FK, `user_id` FK, `played_at` | indexed on `played_at` for explore |
| `song_downloads` | `id` PK, `song_id` FK, `user_id` FK, `downloaded_at` | indexed on `downloaded_at` |
| `user_player_state` | `user_id` PK | persisted queue + index, shuffle order/seed, repeat enum, `manual_next`, current uuid, `queue_sources` JSONB |
| `user_offline_songs` | (`user_id`, `song_id`) PK | server-side hint of which songs the user wants cached on every device |
| `song_share_tokens` | `token` PK | time-limited; default 24 h |
| `edit_jobs` | `id` PK, `source_song_id` FK, status enum, `result_song_id`, `params` JSONB, `error` | `EditJobStatus`: pending, processing, done, failed, duplicate |
| `song_edit_drafts` | (`user_id`, `song_id`) PK | autosaved editor params |
| `import_jobs` | `id` PK, `user_id` FK, `filename`, status enum, `song_id`, `duplicate_of`, `error` | mirrors `EditJobStatus` enum |
| `playlists` | `id` PK, `user_id` FK, `name`, `icon` | `created_at`, `updated_at` |
| `playlist_songs` | (`playlist_id`, `song_uuid`) PK | `position` integer for ordering |
| `error_logs` | `id` PK | inserted by the global exception handler |

### Eligibility (publish bar)

Before a song can become "community" content (visible to other users), `crud._is_publish_eligible` checks the `properties` JSONB blob has all of `trackName`, `artistName`, `collectionName`, `primaryGenreName`, `releaseDate`, and `trackNumber`, plus either `artworkUrl100` or a cached `artwork_thumb`. `routers/library.publish_songs` strips `owner_id` and sets `source='community'` on each successfully validated song. The lighter `EligibleSong` projection used in `GET /library/eligible` checks a smaller subset (track/artist/album/artwork/genre) for UI purposes.

## File storage

Two on-disk directories are configured by `SongbirdServerConfig`:

- `downloads_dir` — one MP3/M4A per song. The download path is recorded in `Song.file_path`. Streaming honors `Range` requests so the browser can seek without buffering the whole file.
- `artwork_dir` — `<artwork_dir>/<song_uuid>/{thumb.jpg,full.jpg}`. Created by `artwork.fetch_and_store_artwork` (iTunes URL) or `store_artwork_from_bytes` (uploaded image). Pillow resizes the source to 200×200 and 600×600 (LANCZOS, JPEG). When Pillow is unavailable, the original bytes are written to both files.

Edits never overwrite the source unless the caller is admin and explicitly asks for `overwrite=True`. The non-overwrite path writes a new song row with `parent_song_id` pointing at the source so the lineage is preserved (`root_song_id` walks all the way back to the original community song).

In Docker, `/songbirdapi/data` is bind-mounted from the host so files survive container rebuilds.
