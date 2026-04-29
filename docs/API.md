# songbirdapi — API reference

All endpoints are mounted under the global `/v1` prefix declared in `songbirdapi/server.py`. The interactive Swagger UI at <http://localhost:8000/docs> is the **source of truth for request/response schemas** — this doc lists routes and intent only.

Auth column legend:
- `cookie` — requires a valid `access_token` cookie (`Depends(get_current_user)`)
- `admin` — requires `role=admin` (`Depends(require_admin)`)
- `public` — no auth required (login, share-link visitors, etc.)

Sources: each section maps 1:1 to a file in `songbirdapi/routers/`.

## auth — `/v1/auth` (`routers/auth.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/login` | public | Verify credentials, set `access_token` + `refresh_token` httpOnly cookies, return user |
| `POST` | `/logout` | public | Clear both auth cookies |
| `POST` | `/refresh` | refresh cookie | Issue a new `access_token` cookie if `refresh_token` is valid |
| `POST` | `/register` | admin | Create a new user (admin-only — there is no public sign-up) |
| `GET` | `/me` | cookie | Return the authenticated user |
| `PATCH` | `/password` | cookie | Change the caller's password (verifies current password) |

## admin — `/v1/admin` (`routers/admin.py`)

All endpoints require `admin` (the router has `dependencies=[Depends(require_admin)]`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/users` | List all users |
| `PATCH` | `/users/{user_id}` | Update role / `is_active` |
| `DELETE` | `/users/{user_id}` | Delete a user (cascades) |
| `GET` | `/stats` | System-level metrics for the admin dashboard |
| `GET` | `/edit-jobs` | Paginated edit-job inspector |
| `GET` | `/errors` | Paginated `error_logs` viewer |

## library — `/v1/library` (`routers/library.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `` | cookie | Return the caller's saved songs (`UserSong`) |
| `GET` | `/eligible` | cookie | Per-song eligibility flags + missing fields (UI subset of the publish bar) |
| `POST` | `/publish` | cookie | Strip ownership and mark `source=community` for caller-owned eligible songs |
| `POST` | `/{song_id}` | cookie | Add a song to the caller's library |
| `DELETE` | `/bulk` | cookie | Remove many at once (`song_ids: list[str]`) |
| `DELETE` | `/{song_id}` | cookie | Remove one |
| `PATCH` | `/{song_id}/position` | cookie | Update `last_position` (player progress checkpoint) |

## offline — `/v1/library/offline` (`routers/offline.py`)

Cross-device hint of which songs the user wants kept offline. Storage of the actual audio bytes lives in the browser (OPFS) — the API only stores IDs.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `` | cookie | List offline song IDs |
| `POST` | `/sync` | cookie | Reconcile a client's set with the server |
| `POST` | `/{song_id}` | cookie | Mark a song as offline-wanted |
| `DELETE` | `/{song_id}` | cookie | Remove |
| `DELETE` | `` | cookie | Clear all |

## songs — `/v1/songs` (`routers/songs.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/` | cookie | List visible songs (community + caller-owned) |
| `GET` | `/library` | cookie | Library-shaped projection used by the web UI |
| `GET` | `/explore` | cookie | Aggregated play/download/library counts; `window=day|week|all` |
| `GET` | `/{id}` | cookie | Single song with properties + artwork flag |
| `POST` | `/{id}/play` | cookie | Record a play event (`song_plays`); UI fires after 30 s of continuous play |
| `GET` | `/{id}/artwork/{size}` | cookie | Stream cached `thumb.jpg` or `full.jpg` |
| `POST` | `/{id}/artwork` | cookie | Upload artwork bytes (validated magic bytes; resized via Pillow) |

## properties — `/v1/properties` (`routers/properties.py`)

All endpoints require `cookie` (declared on the router).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/itunes` | Proxy iTunes search via `songbirdcore.itunes` |
| `GET` | `` | List songs (paginated) for the tagging UI |
| `GET` | `/{song_id}/eligible` | Detailed eligibility — community publish bar, used by editor & library |
| `GET` | `/{id}` | Get one song's properties |
| `PUT` | `` | Update a song's `properties`; triggers background artwork fetch |

## download — `/v1/download` (`routers/downloads.py`)

All endpoints require `cookie`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `` | yt-dlp download by URL; returns existing UUID(s) if URL already in DB unless `ignore_cache` |
| `GET` | `/{id}` | Stream a song file with `Range` support (HTTP 206) |
| `DELETE` | `/{id}` | Delete a song (admin-only inside the handler; cascades remove file + rows) |

## edit — `/v1/edit` (`routers/edit.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/songs/{id}` | cookie | Submit an edit job (`202 Accepted`); ffmpeg runs via `BackgroundTasks` |
| `GET` | `/drafts` | cookie | List the caller's saved drafts |
| `GET` | `/songs/{id}/draft` | cookie | Fetch one draft |
| `PUT` | `/songs/{id}/draft` | cookie | Upsert a draft |
| `DELETE` | `/songs/{id}/draft` | cookie | Delete a draft |
| `GET` | `/jobs/{job_id}` | cookie | Poll job status (`pending → processing → done | failed | duplicate`) |

Edit params: `trim_start`, `trim_end`, `volume`, `fades[]`, `cuts[]` (with optional per-cut `fade_in`/`fade_out`), `speed` (atempo-chained for values outside `[0.5, 2.0]`), `normalize` (`dynaudnorm`). Non-overwrite edits create a new song with `parent_song_id` pointing back. Admin-only `overwrite=True` swaps the source file atomically via a `.tmp` rename.

## import — `/v1/import` (`routers/imports.py`)

Upload pre-existing audio files into the library. Throttled by `asyncio.Semaphore(5)`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `` | cookie | Paginated list of import jobs (pagination + status counts) |
| `POST` | `` | cookie | Multipart upload one or more files; `202 Accepted`; processing happens async |
| `GET` | `/{job_id}` | cookie | Poll a single job |

The web client uploads up to 100 MB per file (configured via `next.config.ts` → `middlewareClientMaxBodySize: '100mb'`). Duplicates are detected and the job lands in `status=duplicate` with `duplicate_of` pointing at the existing UUID.

## playlists — `/v1/playlists` (`routers/playlists.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `` | cookie | List the caller's playlists |
| `POST` | `` | cookie | Create a playlist |
| `PATCH` | `/{playlist_id}` | cookie | Rename / change icon |
| `DELETE` | `/{playlist_id}` | cookie | Delete |
| `GET` | `/{playlist_id}/songs` | cookie | Ordered song list |
| `POST` | `/{playlist_id}/songs` | cookie | Add one |
| `POST` | `/{playlist_id}/songs/bulk` | cookie | Add many |
| `DELETE` | `/{playlist_id}/songs/bulk` | cookie | Remove many |
| `DELETE` | `/{playlist_id}/songs/{song_uuid}` | cookie | Remove one |
| `PATCH` | `/{playlist_id}/songs` | cookie | Reorder |

## player — `/v1/player` (`routers/player.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/state` | cookie | Restore queue, queue index, shuffle/repeat, current uuid, manual-next, queue_sources |
| `PUT` | `/state` | cookie | Persist the same (includes queue_sources array with label, href, id) |

Web client persists every queue mutation including queue sources (context of where the queue originated); on page load `PlayerProvider` restores from this endpoint. `queue_sources` is now server-of-truth (replaced localStorage-only pattern).

## share — `/v1/share` (`routers/share.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/songs/{song_id}` | cookie | Issue a 24 h share token for the caller |
| `GET` | `/{token}/info` | public | Show track metadata (no audio) |
| `GET` | `/{token}/download` | public | Stream audio with `Range` support, no login |

## version (`routers/version.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/v1/version` | public | Build version string from `songbirdapi/version.py` |

## Schemas

For request bodies, response models, status codes, validation rules, and field types, **always check `/docs`**. Pydantic models in each router (`LoginBody`, `DownloadBody`, `EditJobResponse`, etc.) are exported into the OpenAPI document at runtime.
