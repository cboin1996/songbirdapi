# songbirdapi tests

Triage baseline: tag `keebox-beta-1`. All test commands assume cwd = repo root.

## How to run

### Unit tests (no DB, no env vars)

```bash
make test
# or: uv run pytest tests/unit -v
```

Fast (~1s). Pure logic — security helpers, audio editor math.

### Integration tests (requires Postgres)

```bash
# starts a dedicated test DB on the same docker postgres container the dev server uses
make test-integration                # default ENV=test
ENV=dev make test-integration        # run against the dev DB instead (NOT recommended; mixes test data with dev)
```

The Makefile target uses `ENV=$(or $(ENV),test)` so you can override. The
conftest skips collection when `ENV` is unset or not in `(dev, test)`.

#### One-time setup

The `songbirdapi-postgres` container must be running (`make docker-run-postgres`
will start it). The test suite uses a separate database `songbirdapi_test`
on that same container. Create it once:

```bash
docker exec songbirdapi-postgres psql -U songbirdapi -d postgres \
  -c "CREATE DATABASE songbirdapi_test;"
```

Create `test.env` in the repo root (gitignored — same pattern as `dev.env`):

```
api_key=69
jwt_secret=testsecretchangeme
admin_username=testadmin
admin_email=testadmin@test.com
admin_password=Test-Admin-Password-12345
postgres_host=localhost
postgres_port=5432
postgres_db=songbirdapi_test
postgres_user=songbirdapi
postgres_password=songbirdapi
```

The schema is created via `Base.metadata.create_all` at session start (no
Alembic), so no migration step is required.

#### Wiping between runs

The session-scoped fixtures create users + songs and clean them up on teardown,
so back-to-back runs are normally fine. If state gets out of sync (e.g. a run
crashed mid-test), wipe and recreate the DB:

```bash
docker exec songbirdapi-postgres psql -U songbirdapi -d postgres \
  -c "DROP DATABASE IF EXISTS songbirdapi_test;" \
  -c "CREATE DATABASE songbirdapi_test;"
```

## Test isolation strategy

- One Postgres database (`songbirdapi_test`), one async engine, one session
  factory — created at conftest import time.
- The FastAPI `lifespan` does **not** run under `httpx.ASGITransport`, so the
  conftest manually patches `database._engine` and `database._session_factory`
  to point at the test engine. This is required because background tasks
  (edit jobs, imports) and the unhandled-exception handler in `server.py` open
  sessions through the module-level factory, not through the `get_db`
  dependency.
- `app.dependency_overrides[get_db]` routes route-handler sessions through the
  same factory.
- `admin_user`, `regular_user`, `sample_song` are **session-scoped** fixtures —
  they are created once and torn down at the end of the run. Tests must not
  rely on a clean DB between cases.
- An autouse fixture clears `test_client.cookies` before and after every test.
  This is mandatory because `AsyncClient` is session-scoped and httpx
  persists Set-Cookie headers across requests; without the clear, every
  `*_requires_auth` test inherits whichever user logged in last.
- No transaction-rollback per test. State persists across tests within a run.

## Spec inventory

| File                    | Covers                                                         | Notes                                            |
|-------------------------|----------------------------------------------------------------|--------------------------------------------------|
| unit/test_security.py   | password hashing, JWT access/refresh encode+decode             | pure functions                                   |
| unit/test_editor.py     | audio editor cut/fade math (offset translation, filter graphs) | pure functions                                   |
| integration/test_admin.py     | /v1/admin/{stats,errors,users,edit-jobs} RBAC + CRUD     |                                                  |
| integration/test_auth.py      | login/logout/refresh, /me, register, change-password     |                                                  |
| integration/test_downloads.py | POST/GET/DELETE /v1/download                             | does not exercise the actual yt-dlp path         |
| integration/test_edit.py      | save/get/delete draft, create+poll edit job              | jobs run as background tasks against the test DB |
| integration/test_imports.py   | upload mp3/m4a, list, get, isolation between users       | uses minimal mp3 byte string                     |
| integration/test_library.py   | add/remove/list, bulk remove, position update, publish   |                                                  |
| integration/test_player.py    | GET/PUT /v1/player/state, queue persistence              |                                                  |
| integration/test_playlists.py | CRUD, songs, reorder, bulk add, cross-user isolation     |                                                  |
| integration/test_properties.py| search, by-id lookup, PUT, /itunes proxy                 |                                                  |
| integration/test_share.py     | create share token, info, download via token             |                                                  |
| integration/test_songs.py     | list, library subset, explore windows, play count, art  | artwork GET requires `/{id}/artwork/{size}`      |
| integration/test_version.py   | GET /v1/version returns version string                   |                                                  |

## Punch list (real source bugs found at keebox-beta-1)

These are **failing tests** that point at source bugs, not test bugs. They are
marked `pytest.mark.xfail(strict=True)` so the suite stays green and the
markers will turn red the moment the source is fixed.

| # | Symptom                                                         | Where                                | Suspected fix                                                                 |
|---|-----------------------------------------------------------------|--------------------------------------|--------------------------------------------------------------------------------|
| 1 | `PATCH /v1/library/{id}/position` returns **204** when entry is missing; should be 404 | `songbirdapi/routers/library.py:158-160` | Replace `Response(204)` with `raise HTTPException(404)` when `crud.update_position` returns None |
| 2 | `PUT /v1/properties` returns **500** when `song.file_path` doesn't exist; should be 422 (or 404 / 409 — anything but a server error for a missing file) | `songbirdapi/routers/properties.py:172-177` | Return `HTTP_422_UNPROCESSABLE_ENTITY` (or 404). The condition is recoverable client-side, not a server fault. Test fixture also needs a real mp3 to exercise the happy path. |

## Watch list

- **Cookie persistence deprecation** — httpx warns about per-request `cookies=`
  args. Many tests still pass `cookies=login.cookies` instead of relying on
  the client jar. Works today because the autouse fixture clears the jar; if
  httpx removes per-request cookies entirely, tests will need refactor.
- **`itunes` proxy** — `test_get_itunes_returns_list` accepts 200/500/502/503
  because the upstream Apple search may be reachable or rate-limited from the
  test host. Not flaky in practice today, but it WILL be on a flaky network.
- **No transactional isolation** — tests within a run share state. Most are
  defensive, but adding a parallel test runner (`-n auto`) would break them.
- **`sample_song` has a non-existent `file_path`** — fine for tests that only
  read metadata, but blocks any test that tries to actually tag/edit/transcode
  the file. See punch list #2.
- **Background tasks share the test DB engine** — fine, but if a test spawns a
  long-running background task and the test session ends before it finishes,
  you'll see `Event loop is closed` warnings. None observed at this baseline.

## Triage diff vs. keebox-beta-1

What was changed in `tests/`:

- `tests/integration/conftest.py` — initialise `database._session_factory` so
  background tasks and the global exception handler can open sessions; add
  autouse cookie-clearing fixture.
- 7 trailing-slash URLs corrected (`/v1/download/` → `/v1/download`,
  `/v1/properties/` → `/v1/properties`).
- `test_get_draft` — assert `body["params"]["trim_start"]` (matches the
  `DraftResponse` schema), not `body["trim_start"]`.
- `test_publish_returns_count` — send the required `{"song_ids": []}` body.
- `test_get_artwork_*` — call `/{id}/artwork/full` (the route requires a
  size segment).
- `test_update_position_not_in_library_returns_404` — `xfail(strict)` (punch
  list #1).
- `test_put_properties` — `xfail(strict)` (punch list #2).

What was changed in `Makefile`:

- `test-integration` now uses `ENV=$(or $(ENV),test)` instead of hardcoded
  `ENV=dev`, so the suite defaults to the test DB.

What needs to exist locally (gitignored, not committed):

- `test.env` at the repo root — see "One-time setup" above for contents.

No `songbirdapi/` source changes.
