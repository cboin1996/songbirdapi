# songbirdapi — deployment

Live instance: <https://songbird.kee-flix.com>

## CI/CD overview

| Event | What happens |
|---|---|
| PR → main | version check + unit + integration tests |
| Push to main | Docker image built and pushed to Docker Hub (`cboin/songbirdapi:latest` + SHA tag) |
| Tag `v*` | Docker push + GitHub Release created + keebox deploy triggered |

Deploy flow on keebox (tag-triggered):
1. `docker system prune -f` — reclaim space
2. `docker-compose pull songbirdapi` — pull new image from Hub
3. `docker-compose run --rm --entrypoint alembic songbirdapi upgrade head` — run migrations
4. `docker-compose up -d songbirdapi` — restart with new image

## Versioning

Every PR must bump both `songbirdapi/version.py` and `pyproject.toml` — the `version-check` CI job enforces this.

## CI deploy key setup (one-time)

Generate a dedicated keypair and register it:

```bash
ssh-keygen -t ed25519 -C "songbirdapi-ci" -f ~/.ssh/songbirdapi_ci_deploy -N ""
ssh-copy-id -i ~/.ssh/songbirdapi_ci_deploy.pub -p 223 <keebox-user>@<keebox-host>
```

Set GitHub secrets in both repos (do not commit key values):

```bash
gh secret set KEEBOX_SSH_KEY -R cboin1996/songbirdapi < ~/.ssh/songbirdapi_ci_deploy
gh secret set KEEBOX_SSH_KEY -R cboin1996/songbirdweb < ~/.ssh/songbirdapi_ci_deploy
gh secret set KEEBOX_HOST    -R cboin1996/songbirdapi  # value: keebox hostname
gh secret set KEEBOX_HOST    -R cboin1996/songbirdweb
gh secret set KEEBOX_USER    -R cboin1996/songbirdapi  # value: keebox ssh user
gh secret set KEEBOX_USER    -R cboin1996/songbirdweb
```

Private key lives at `~/.ssh/songbirdapi_ci_deploy` on cboin's machine.

## Host

See `KEEBOX_HOST` / `KEEBOX_USER` secrets. SSH port 223.

Local alias (cboin's `~/.ssh/config`):
```
Host kee-flix.com
  AddressFamily inet
  Port 223
  User <KEEBOX_USER>
```

## Domain + nginx routing

SSL terminated at host nginx (Nginx Proxy Manager).

| Path | Forwarded to |
|---|---|
| `/v1/*` | `http://127.0.0.1:9669` (songbirdapi) |
| `/*` | `http://127.0.0.1:6996` (songbirdweb) |

NPM config note: **Forward Scheme must be `http`** (not `https`). Also requires `client_max_body_size 100m;` in custom nginx config so `/v1/import` uploads don't 413.

## Container ports

| Service | Host:container |
|---|---|
| songbirdapi | `9669:8000` |
| songbirdweb | `6996:3000` |
| postgres | internal only (Docker network) |

## Storage layout

```
/mnt/jellydisk3/songbird/
├── postgres/         # postgres data volume
└── data/
    ├── downloads/    # MP3 / M4A files
    └── artwork/      # <song_uuid>/{thumb,full}.jpg
```

Note: API container writes files as root (UID 0). Cleaning from the host requires `sudo` or a temp container with the same volume mount.

## keebox layout

```
~/songbird/
├── docker-compose.yml   # source of truth: the songbird-keebox repo
├── .env                 # prod secrets (NOT committed)
```

## `.env` template

```bash
# Postgres
POSTGRES_DB=<name>
POSTGRES_USER=<user>
POSTGRES_PASSWORD=<password>

# API
API_KEY=<random>
JWT_SECRET=<long-random-string>
CORS_ORIGINS=https://songbird.kee-flix.com

# Seeded admin (created on first boot)
ADMIN_USERNAME=<username>
ADMIN_EMAIL=<email>
ADMIN_PASSWORD=<password>

# Optional session and cookie settings (defaults shown; docker-compose.yml passes them through)
# COOKIE_SECURE=true
# SESSION_IDLE_DAYS=30
# SESSION_ABSOLUTE_DAYS=90
# SESSION_MAX_PER_USER=10
# REFRESH_REPLAY_WINDOW_SECONDS=60
# REFRESH_REUSE_DETECTION=true
```

> Any new field added to `SongbirdServerConfig` in `settings.py` must be added here before redeploying, otherwise the container will crash on boot.

## First-time keebox setup

```bash
# storage
sudo mkdir -p /mnt/jellydisk3/songbird/{postgres,data/downloads,data/artwork}
sudo chown -R <keebox-user>:<keebox-user> /mnt/jellydisk3/songbird

# app dir
mkdir -p ~/songbird && cd ~/songbird
# copy docker-compose.yml from songbird-keebox repo and create .env from template above

# run migrations and start
docker-compose run --rm --entrypoint alembic songbirdapi upgrade head
docker-compose up -d
docker-compose logs -f --tail 50
```

## Manual deploy / rollback

```bash
cd ~/songbird
docker system prune -f
docker-compose pull songbirdapi
docker-compose run --rm --entrypoint alembic songbirdapi upgrade head
docker-compose up -d songbirdapi
```

Rollback to a prior tag:
```bash
docker-compose stop songbirdapi
# set the prior image tag in the compose file or env, then:
docker-compose pull songbirdapi
docker-compose up -d songbirdapi
```
Do not roll back by re-running the old tag's deploy workflow, and do not run `alembic upgrade head` with the old image: it fails with `No such revision` because the database is already at the session migration, and `set -e` stops the deploy before the image switches. Afterwards, unpin the old tag. Run `alembic downgrade` only when a migration changes data the old code reads. The session migration is not one: the old image ignores `auth_sessions`, and startup `create_all` leaves the existing table alone. A downgrade would drop the table, and while it runs the new container, if still up, answers every authenticated request with a 500.

## Sessions: deploy, rollback, risks

- **Deploy order: either.** The new web middleware works against the old API (it forwards the rotated cookie only if the API sends one). The new API with the old middleware also works: the old middleware drops the rotated refresh cookie, so the browser keeps presenting the token it already had, which the API treats as a replay or a branch and never as reuse. It costs a few extra branches until web ships, so the release command's API-first order is fine.
- **Nothing needs to change on keebox for the release.** Every new setting has a default that matches production (`COOKIE_SECURE=true`, 30 d idle, 90 d cap, 10 sessions, 60 s window, reuse detection on). Only to change one of them, add its line to the API's `environment:` in `~/songbird/docker-compose.yml`; the `songbird-keebox` repo's `docker-compose.yml` (the source of truth for that file) already lists all six.
- **First deploy logs everyone out once.** Tokens issued before sessions existed have no `sid` and get 401. Tell users before the release; nothing in the deploy does it.
- **Rollback to the old API** turns refresh tokens back into stateless tokens that live as long as their `exp` (up to 90 days) with no revocation, so keep it brief. Sessions created by the new code survive the rollback and work again after rolling forward, but a password change made during the rollback does not revoke them. Tokens the old code issued have no `sid`, so those users sign in once more after rolling forward.
- **Watch the logs after deploy** for `refresh token reuse: revoked session`. A few are theft or a stale browser; a stream of them from users who were only using the app means false logouts. To stop revoking while you investigate (reuse is then logged and branched), set `REFRESH_REUSE_DETECTION=false` in `~/songbird/.env` and run `docker-compose up -d songbirdapi`. `restart` does not re-read `.env`, and the variable only reaches the container if `~/songbird/docker-compose.yml` lists it (add the line from the `songbird-keebox` repo's copy first). A value other than `true`/`false` stops the API from booting. At startup the API logs `sessions: idle=… reuse_detection=… cookie_secure=…`; check it to confirm the setting took.
- **Accepted risks of the design:**
  - A refresh token one generation old stays usable until the current holder refreshes again. While a user is idle (up to 30 days) a copy from a backup or proxy log could take the session over; it is noticed when the user returns.
  - With `refresh_reuse_detection=false`, any token ever issued in a session is valid until logout, idle expiry or the 90-day cap.
  - An access token is checked against the session on every request, so logout and password change take effect at once; idle expiry is only enforced at refresh.

## Quick reference

| Thing | Command |
|---|---|
| Tail API logs | `docker-compose logs -f --tail 100 songbirdapi` |
| Tail web logs | `docker-compose logs -f --tail 100 songbirdweb` |
| Restart API | `docker-compose restart songbirdapi` |
| Open psql | `docker exec -it songbird-postgres psql -U $POSTGRES_USER -d $POSTGRES_DB` |
| Apply migrations | `docker-compose run --rm --entrypoint alembic songbirdapi upgrade head` |
| Prune images | `docker system prune -f` |
| Check disk | `du -sh /mnt/jellydisk3/songbird/*` |
