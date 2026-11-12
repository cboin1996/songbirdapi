# songbirdapi

FastAPI backend for the Songbird music streaming ecosystem. Handles song downloads (via `songbirdcore`/yt-dlp), HTTP-range audio streaming, iTunes metadata tagging, artwork caching, async ffmpeg edit jobs, JWT cookie auth, and per-user library/player-state persistence in PostgreSQL.

## Stack

- **FastAPI** (async)
- **SQLAlchemy 2.x async** + **asyncpg** + **PostgreSQL 16**
- **Alembic** for schema migrations
- **uv** for dependency management
- **PyJWT** + bcrypt for auth
- **ffmpeg** subprocesses for audio editing
- **Pillow** for artwork resizing
- **songbirdcore** for yt-dlp/iTunes integration

## Ecosystem

| Repo | Role |
|---|---|
| `songbirdcore` | Shared Python lib — yt-dlp wrapper, iTunes API client, ID3 tagging |
| `songbirdcli` | CLI tool — uses `songbirdcore` directly |
| **`songbirdapi`** | **This repo — FastAPI service consumed by `songbirdweb`** |
| `songbirdweb` | Next.js 15 browser UI |

Docker images (`cboin/songbirdapi`) are built multi-arch (`amd64` + `arm64`).

## Quick start

```bash
make setup                     # uv sync --extra dev
make docker-run-postgres       # spin up postgres:16-alpine on :5432
ENV=dev make local-run         # uvicorn --reload on :8000
```

> **Important:** `make local-run` alone fails because `SongbirdServerConfig` requires `jwt_secret` and `postgres_password`. Always set `ENV=dev` so `dev.env` is loaded.

Interactive docs: <http://localhost:8000/docs>.

For migrations, deploy, or schema details, see [`docs/`](./docs/).

## Make targets

| Target | What it does |
|---|---|
| `make setup` | `uv sync --extra dev` |
| `make upgrade` | `uv lock --upgrade && uv sync --extra dev` |
| `make lint` | `uv run black songbirdapi/.` |
| `make test` | unit tests (`tests/unit/`) |
| `make test-integration` | integration tests — needs `ENV=dev` and live Postgres |
| `make migrate` | `uv run alembic upgrade head` |
| `make local-run` | start uvicorn (must prefix `ENV=dev`) |
| `make dev-wipe` | drop dev DB, wipe `data/`, rerun migrations |
| `make docker-build` | build local image |
| `make docker-run-postgres` | run postgres container on the `songbirdapi` bridge network |
| `make docker-connect-postgres` | open `psql` shell inside the postgres container |
| `make docker-stop-postgres` | stop + remove the postgres container |
| `make docker-run-songbirdapi` | run prebuilt image with `docker.env` |
| `make docker-run-all` | postgres + api together |
| `make docker-stop-all` | stop both |
| `make docker-clean-all` | stop + remove containers and network |
| `make docker-dev` | clean + build + run all (full reset) |
| `make volumes` | create `data/` directories |

## Environment variables

Config is loaded from `<ENV>.env` at the repo root (selected by the `ENV` env var). The Docker container reads `docker.env` via `--env-file`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `api_key` | yes | — | Static API key (reserved) |
| `jwt_secret` | yes | — | Secret for signing JWT access + refresh tokens |
| `admin_username` | no | `""` | Username of the admin account seeded on startup (skipped if blank) |
| `admin_email` | no | `""` | Email of the seeded admin |
| `admin_password` | no | `""` | Password of the seeded admin |
| `session_idle_days` | no | `30` | A session dies after this many days without a refresh |
| `session_absolute_days` | no | `90` | A session dies this many days after login, however active |
| `refresh_replay_window_seconds` | no | `60` | How long after a rotation the previous token is still accepted |
| `refresh_reuse_detection` | no | `true` | `false`: a reused refresh token is branched instead of revoking the session (kill switch) |
| `session_max_per_user` | no | `10` | Live sessions per user; a login beyond this signs out the least recently used |
| `cookie_secure` | no | `true` | `Secure` flag on the auth cookies. Set `COOKIE_SECURE=false` for local development over plain HTTP (Safari drops `Secure` cookies on `http://localhost`) |
| `cors_origins` | no | `http://localhost:3000` | Comma-separated list of allowed CORS origins |
| `postgres_host` | no | `localhost` | PostgreSQL host (`songbirdapi-postgres` in Docker) |
| `postgres_port` | no | `5432` | PostgreSQL port |
| `postgres_db` | no | `songbirdapi` | Database name |
| `postgres_user` | no | `songbirdapi` | DB user |
| `postgres_password` | yes | — | DB password |
| `downloads_dir` | no | `<root>/data/downloads` | Where audio files land |
| `artwork_dir` | no | `<root>/data/artwork` | Where cached artwork lives |

> Any new `SongbirdServerConfig` fields must be added to the production `docker.env` before deploying. The session and cookie settings above all have defaults, so production only needs them to change one.

## Deeper docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — request lifecycle, modules, schema, auth, file storage
- [`docs/API.md`](docs/API.md) — endpoint catalog by router (FastAPI auto-docs at `/docs` is the source of truth for schemas)
- [`docs/MIGRATIONS.md`](docs/MIGRATIONS.md) — Alembic autogenerate workflow
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — keebox beta deploy runbook

## Development notes

- **Branches:** never commit to `main`; always work on a feature branch.
- **Testing:** unit tests in `tests/unit/`, integration tests in `tests/integration/`. Integration tests must not run in CI.
- **Linting:** `make lint` (black). CI runs `black --check` on every PR.
- **Docker CI:** PRs build multi-arch without pushing. Merges to `main` and tags push to `cboin/songbirdapi`.
- **Dev seeding:** `ENV=dev uv run python scripts/seed_dev.py` populates fake play/download/library data so explore queries return something.
