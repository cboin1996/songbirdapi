# songbirdapi

FastAPI backend for the Songbird music streaming ecosystem. Handles song downloads (via `songbirdcore`/yt-dlp), file streaming with HTTP range requests, iTunes metadata tagging, artwork caching, async audio editing (ffmpeg), user auth, and per-user library/player-state persistence. Stores all data in PostgreSQL via SQLAlchemy async + asyncpg.

## Ecosystem

Songbird has four repos:

| Repo | Role |
|---|---|
| `songbirdcore` | Shared Python library — yt-dlp wrapper, iTunes API client, ID3 tagging |
| `songbirdcli` | CLI tool — downloads songs using `songbirdcore` |
| **`songbirdapi`** | **This repo — FastAPI service consumed by the web UI** |
| `songbirdweb` | Next.js 15 browser UI |

`songbirdapi` depends on `songbirdcore` for download and tagging logic. It serves `songbirdweb` over HTTP. The Docker image (`cboin/songbirdapi`) targets `linux/amd64` and `linux/arm64` (Raspberry Pi production).

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)
- PostgreSQL 16 (or Docker)
- ffmpeg (required for audio editing)

## Setup & Running Locally

**1. Install dependencies**

```bash
make setup
# equivalent: uv sync --extra dev
```

**2. Start PostgreSQL**

```bash
make docker-run-postgres
# runs postgres:16-alpine on localhost:5432
# db/user/password all default to "songbirdapi"
```

Or point `dev.env` at an existing Postgres instance.

**3. Configure `dev.env`**

The checked-in `dev.env` contains dev defaults. Edit secrets before running against real data. The file is selected automatically when `ENV=dev`.

**4. Run the API**

```bash
ENV=dev make local-run
# equivalent: ENV=dev uv run uvicorn songbirdapi.server:app --host 0.0.0.0 --reload
```

Server starts on `http://localhost:8000`. Interactive docs at `/docs`.

**Docker (all-in-one)**

```bash
make docker-dev
# builds image, starts postgres + api containers on the "songbirdapi" bridge network
```

The API container reads `docker.env` and mounts `./data/songbirdapi/downloads` for song files.

**VSCode debugger**

Add to `.vscode/launch.json`:

```json
{
    "name": "Songbird: API",
    "type": "python",
    "request": "launch",
    "module": "uvicorn",
    "args": ["songbirdapi.server:app", "--reload", "--log-level", "debug"],
    "jinja": true,
    "justMyCode": true,
    "envFile": "./dev.env"
}
```

## Environment Variables

Config is loaded from `<ENV>.env` at repo root. Set `ENV=dev` to load `dev.env`. The Docker container passes `docker.env` via `--env-file`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `api_key` | yes | — | Static API key (reserved) |
| `jwt_secret` | yes | — | Secret for signing JWT access and refresh tokens |
| `admin_username` | no | `""` | Username of the admin account seeded on startup (skipped if blank) |
| `admin_email` | no | `""` | Email of the seeded admin account |
| `admin_password` | no | `""` | Password of the seeded admin account |
| `cors_origins` | no | `http://localhost:3000` | Comma-separated list of allowed CORS origins |
| `postgres_host` | no | `localhost` | PostgreSQL host (`songbirdapi-postgres` in Docker) |
| `postgres_port` | no | `5432` | PostgreSQL port |
| `postgres_db` | no | `songbirdapi` | PostgreSQL database name |
| `postgres_user` | no | `songbirdapi` | PostgreSQL user |
| `postgres_password` | yes | — | PostgreSQL password |
| `downloads_dir` | no | `<root>/data/downloads` | Directory where audio files are stored |
| `artwork_dir` | no | `<root>/data/artwork` | Directory where cached artwork is stored |

> Any new `SongbirdServerConfig` fields must be added to the production `docker.env` before deploying.

## Key Concepts & Data Model

**Schema** — created by `Base.metadata.create_all` on startup (no migration framework):

| Table | Purpose |
|---|---|
| `users` | Accounts with `admin` or `user` role, bcrypt-hashed passwords |
| `songs` | Downloaded audio files; `properties` is a JSONB iTunes metadata blob; `parent_song_id` links edit children back to originals |
| `user_songs` | Per-user library (songs ↔ users many-to-many), stores `last_position` and `last_played_at` |
| `song_plays` | Play event log used for popularity and explore queries |
| `song_downloads` | Download event log |
| `user_player_state` | Persisted queue, queue index, shuffle, and repeat mode per user |
| `song_share_tokens` | Time-limited unauthenticated share links (24 h default) |
| `edit_jobs` | Async ffmpeg edit jobs; statuses: `pending → processing → done | failed` |
| `song_edit_drafts` | Per-user saved edit parameters before submitting a job |

**Auth**: `POST /auth/login` sets two httpOnly cookies (`access_token`, `refresh_token`). All protected routes read `access_token` from cookies via `Depends(get_current_user)`. `POST /auth/refresh` issues a new access token. User registration requires an admin caller.

**Streaming**: `GET /download/{id}` handles `Range` request headers (HTTP 206), enabling seek without buffering the whole file. The same range logic is used for unauthenticated share downloads at `GET /share/{token}/download`.

**Audio editing**: `POST /edit/songs/{id}` creates an `EditJob` and runs ffmpeg asynchronously via `BackgroundTasks`. Supported params: `trim_start`, `trim_end`, `volume`, `fade_in`, `fade_out`. Non-overwrite edits produce a new `Song` row with `parent_song_id` pointing to the source. Overwrite is admin-only and replaces the source file atomically via a `.tmp` swap.

**Artwork**: Tagging a song via `PUT /properties` triggers a background download of 300×300 and 600×600 JPEG artwork from the iTunes CDN into `artwork_dir/<song_uuid>/`. Cached artwork is served at `GET /songs/{id}/artwork?size=thumb|full`.

**Explore**: `GET /songs/explore?window=day|week|all` aggregates play/download/library counts from indexed event tables and returns global and per-user stats. Song search uses a GIN full-text index over `trackName`, `artistName`, and `collectionName` in the `properties` JSONB column.

## Development Notes

**Branches**: never commit to `main`; use feature branches.

**Testing**:

```bash
make test                # unit tests, no DB required
make test-integration    # integration tests — requires ENV=dev and a running Postgres
```

Unit tests are in `tests/unit/`, integration tests in `tests/integration/`. Integration tests must not run in CI.

**Linting**:

```bash
make lint   # runs black
```

CI runs `black` style check on every PR (`.github/workflows/style.yml`).

**Docker CI**: PRs build multi-arch images (`amd64` + `arm64`) without pushing. Merges to `main` and version tags push to `cboin/songbirdapi` on Docker Hub.

**Dev data seeding**: After downloading some songs locally, populate fake play/download/library data for explore queries:

```bash
ENV=dev uv run python scripts/seed_dev.py
```

**Schema changes**: There is no migration tool. For schema changes in development, write ALTER statements manually or drop and recreate the database. On first startup against a fresh database, `create_all` builds the full schema automatically.
