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
├── docker-compose.yml   # pulled from songbird-keebox repo
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
docker-compose pull cboin/songbirdapi:<prior-tag>
docker-compose run --rm --entrypoint alembic songbirdapi downgrade <prior-rev>
docker-compose up -d songbirdapi
```

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
