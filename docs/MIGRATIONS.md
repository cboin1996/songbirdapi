# songbirdapi — migrations

Schema changes are managed by **Alembic** in async mode (`migrations/env.py` uses `async_engine_from_config`). The Postgres DSN comes from `alembic.ini` (default `postgresql+asyncpg://songbirdapi:songbirdapi@localhost:5432/songbirdapi`).

> **Always autogenerate. Never hand-write a migration.** Hand-written DDL is error-prone — autogenerate diffs the live DB against `Base.metadata` (`songbirdapi/models.py`) and produces correct DDL automatically. Hand-written diffs go out of sync with the model layer and cause silent breakage on the next autogen run.

## Standard flow

1. **Edit `songbirdapi/models.py`** — add/change/remove columns, indexes, FKs.
2. **Make sure your local DB is at `head`:**
   ```bash
   make migrate
   ```
3. **Autogenerate the new revision:**
   ```bash
   ENV=dev uv run alembic revision --autogenerate -m "short description"
   ```
   The new file lands in `migrations/versions/<rev>_<slug>.py`.
4. **Review the file.** Strip noise. Autogenerate sometimes detects:
   - DB objects that are not modeled (e.g. legacy `request_logs` table, stale `idx_songs_fts`, dangling FK constraints on `songs_owner_id_fkey`)
   - Tables you don't own
   - Indexes that the DB has but the model doesn't declare (or vice versa)

   These show up as `op.drop_*` / `op.create_*` calls unrelated to your change. Delete them. Only keep ops that match the model edit you actually made.
5. **Apply the migration:**
   ```bash
   make migrate    # alembic upgrade head
   ```
6. **Sanity check:** restart the API, hit the affected endpoints, run unit + integration tests.
7. **Commit `models.py` + the new migration file together** in a single semantic commit (e.g. `feat(api): add song_share_tokens.expires_at`).

## Why we never hand-write

`Base.metadata.create_all` runs on every API boot (see `database.create_schema`). This works fine on a fresh DB but does **not** apply incremental changes to an existing one. Alembic is the only mechanism that keeps prod, dev, and CI in sync. Autogenerate guarantees the migration matches what SQLAlchemy actually expects — hand-writing the DDL means the migration and the ORM can drift, leading to runtime crashes that only show up after deploy.

## Wiping + re-migrating in dev

When schemas drift badly (e.g. after pulling a branch with multiple migrations), reset:

```bash
ENV=dev make dev-wipe
```

What this does (see `Makefile`):

1. Terminates open connections to the `songbirdapi` database.
2. Drops `songbirdapi`, recreates it empty.
3. Wipes `data/artwork/`, `data/downloads/`, `data/songbirdapi/downloads/` on disk.
4. Runs `make migrate` to bring the empty DB up to `head`.
5. Reminds you to clear browser site data (cookies, OPFS audio, IndexedDB).

After `dev-wipe`, restart the API so the lifespan handler runs `seed_admin` again from `dev.env`.

## Common Alembic commands

```bash
ENV=dev uv run alembic current                           # show current head
ENV=dev uv run alembic history                           # full revision graph
ENV=dev uv run alembic upgrade head                      # apply all pending
ENV=dev uv run alembic downgrade -1                      # roll back one
ENV=dev uv run alembic revision --autogenerate -m "msg"  # generate
ENV=dev uv run alembic upgrade <rev>                     # jump to a specific rev
ENV=dev uv run alembic stamp head                        # mark DB as up-to-date without running scripts
```

## Production / keebox

Migrations run inside the API container at startup-equivalent moments — see `docs/DEPLOYMENT.md`. After updating the repo on keebox:

```bash
cd ~/songbird
docker compose run --rm songbirdapi alembic upgrade head
docker compose up -d
```

Run migrations from a one-shot container (the `--rm` form) before bringing the service up — that way the running app boots against the new schema. Alternatively, a future `entrypoint.sh` wrapper could `alembic upgrade head` automatically on container start; today that wrapper does not exist.

## Recent migrations

- **`2f5adcc84df4_add_queue_sources_to_user_player_state.py`** (keebox-beta-1+): Adds `queue_sources` JSONB column to `user_player_state`. Clients now send queue metadata (source label, href, playlist ID) to restore playback context on reload.

## Adding a brand-new migration directory

If you ever wipe `migrations/versions/`, restart fresh:

```bash
ENV=dev uv run alembic revision --autogenerate -m "baseline"
```

The current baseline `4ca3ca774ca4_baseline.py` was created from a fully populated dev DB and stripped of legacy objects. New revisions chain off it via `down_revision`.
