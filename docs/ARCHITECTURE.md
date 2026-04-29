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
| `songbirdapi/dependencies.py` | `get_current_user` (decode JWT cookie), `require_admin`, `load_settings`, `process_song_url` |
| `songbirdapi/security.py` | Password hashing (bcrypt), `create_access_token`/`create_refresh_token` (15 min / 7 day), `decode_token` |
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

| Token | Lifetime | Cookie | Type claim |
|---|---|---|---|
| Access | 15 min | `access_token` (httpOnly, samesite=lax) | `access` |
| Refresh | 7 days | `refresh_token` (httpOnly, samesite=lax) | `refresh` |

- `POST /v1/auth/login` validates credentials with bcrypt and writes both cookies.
- `Depends(get_current_user)` reads `access_token` from cookies, decodes with `jwt_secret`, asserts `type=access`, then loads the `User`. 401 on any failure.
- `POST /v1/auth/refresh` rotates the access cookie if the refresh cookie is still valid.
- `POST /v1/auth/logout` deletes both cookies.
- `Depends(require_admin)` chains `get_current_user` and asserts `role=admin`.
- `POST /v1/auth/register` is gated behind `require_admin` — there is no public sign-up.

The browser keeps the cookies httpOnly so JS can't read them; `songbirdweb`'s middleware refreshes the access cookie transparently when expired.

## Postgres schema

All tables live in the `public` schema and are managed by Alembic. The schema is also created from models on first boot (`Base.metadata.create_all` in the lifespan handler) so a fresh DB works out of the box.

| Table | Key fields | Notes |
|---|---|---|
| `users` | `id` PK, `username` U, `email` U, `role` enum(`admin`/`user`), `is_active` | bcrypt `hashed_password` |
| `songs` | `uuid` PK, `url`, `file_path`, `properties` JSONB, `artwork_thumb`, `artwork_full`, `parent_song_id` FK, `root_song_id` FK, `owner_id`, `source` | GIN index on `properties`; `parent_song_id` chains edit children |
| `user_songs` | (`user_id`, `song_id`) PK | per-user library; tracks `last_position`, `last_played_at` |
| `song_plays` | `id` PK, `song_id` FK, `user_id` FK, `played_at` | indexed on `played_at` for explore |
| `song_downloads` | `id` PK, `song_id` FK, `user_id` FK, `downloaded_at` | indexed on `downloaded_at` |
| `user_player_state` | `user_id` PK | persisted queue + index, shuffle order/seed, repeat enum, `manual_next`, current uuid |
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
