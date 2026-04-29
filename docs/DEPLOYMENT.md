# songbirdapi — deployment (keebox beta)

This is the manual beta-deploy runbook for the live instance at <https://songbird.kee-flix.com>. Future automation will follow the `keebox-app-template` pattern (build to GHCR, SSH + pull on keebox), but until that lands, every push to keebox is manual.

## Status as of 2026-04-29

- **Live URL:** <https://songbird.kee-flix.com>
- **Tagged SHAs (`keebox-beta-1` on both repos):**
  - songbirdapi: `b022e95` on `songbirdapi-enhancements`
  - songbirdweb: `9d505ca` on `songbirdweb-enhancements`
- **songbirdcore:** `0.1.9` from PyPI (pinned via `uv.lock`)
- **Postgres:** 16 alpine

To diff what has drifted from the live tag: `git diff keebox-beta-1` in each repo.

## Host

```
keenan@kee-flix.com -p 223
```

(SSH alias `kee-flix.com` is configured in `~/.ssh/config` — port 223 is the canonical entry.)

## Domain + nginx routing

SSL is terminated at the host nginx (managed by Keenan via NPM — Nginx Proxy Manager).

| Path | Forwarded to |
|---|---|
| `/v1/*` | `http://127.0.0.1:9669` (songbirdapi) |
| `/*` | `http://127.0.0.1:6996` (songbirdweb) |

Reference snippet (already configured on the host):

```nginx
location /v1/ {
    proxy_pass http://127.0.0.1:9669;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
location / {
    proxy_pass http://127.0.0.1:6996;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## Container ports (host:container)

| Service | Mapping |
|---|---|
| songbirdweb | `6996:3000` |
| songbirdapi | `9669:8000` |
| postgres | not exposed externally; reached over the `songbird` Docker network |

## Storage layout

```
/mnt/jellydisk3/songbird/
├── postgres/             # postgres:16-alpine data volume
└── data/
    ├── downloads/        # MP3 / M4A files
    └── artwork/          # <song_uuid>/{thumb,full}.jpg
```

The directory tree is created once via `sudo` and chown'd to `keenan:keenan`. Note: the API container creates files inside `/songbirdapi/data` as **root (UID 0)**, so cleaning files from the host requires `sudo` or a temp container with the same volume mount. This is the temporary home shared with jellyfin until the dedicated 4 TB drive is installed.

## Layout on keebox

```
~/songbird/
├── docker-compose.yml      # canonical compose (clone of songbird-keebox/docker-compose.yml)
├── .env                    # prod secrets (NOT committed)
├── songbirdapi/            # cloned repo, on songbirdapi-enhancements branch
└── songbirdweb/            # cloned repo, on songbirdweb-enhancements branch
```

## One-time setup

```bash
ssh kee-flix.com   # alias, port 223

# storage
sudo mkdir -p /mnt/jellydisk3/songbird/{postgres,data}
sudo chown -R keenan:keenan /mnt/jellydisk3/songbird

# app dir
mkdir -p ~/songbird && cd ~/songbird

# clone repos at feature branches (public repos, no auth needed)
git clone -b songbirdapi-enhancements https://github.com/cboin1996/songbirdapi.git
git clone -b songbirdweb-enhancements https://github.com/cboin1996/songbirdweb.git
```

Copy `docker-compose.yml` from `~/proj/cboin1996/songbird-keebox/docker-compose.yml` → `~/songbird/docker-compose.yml`. Copy `.env.example` → `~/songbird/.env` and fill real secrets.

### `.env` template

```bash
# ---- Postgres ----
POSTGRES_DB=songbird
POSTGRES_USER=songbird
POSTGRES_PASSWORD=CHANGEME

# ---- API secrets ----
API_KEY=CHANGEME
JWT_SECRET=CHANGEME_USE_LONG_RANDOM_STRING
CORS_ORIGINS=https://songbird.kee-flix.com

# ---- Seeded admin (created on first boot) ----
ADMIN_USERNAME=cboin
ADMIN_EMAIL=cboin1996@gmail.com
ADMIN_PASSWORD=CHANGEME
```

> Any new `SongbirdServerConfig` field in `songbirdapi/settings.py` must be added here **before** you redeploy, otherwise the container will crash on boot.

## Build + start

```bash
cd ~/songbird
docker compose build      # ~5–10 min for the api image (multi-arch toolchain)
docker compose up -d
docker compose logs -f --tail 50
```

## Verify

```bash
curl -s http://localhost:9669/v1/version    # api up
curl -sI http://localhost:6996/             # web up
```

Browse: <https://songbird.kee-flix.com>. Login with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from `.env`.

## Update an existing deploy

```bash
cd ~/songbird/songbirdapi && git pull
cd ~/songbird/songbirdweb && git pull
cd ~/songbird

# run migrations *before* swapping to the new image
docker compose run --rm songbirdapi alembic upgrade head

docker compose build
docker compose up -d
docker image prune -f      # reclaim space from old layers
```

## Rollback

If a deploy breaks something:

```bash
cd ~/songbird/songbirdapi && git checkout keebox-beta-1
cd ~/songbird/songbirdweb && git checkout keebox-beta-1
cd ~/songbird
docker compose build
docker compose up -d
```

If the rollback also requires a DB downgrade:

```bash
docker compose run --rm songbirdapi alembic downgrade <prior-rev>
docker compose up -d
```

If the schema can't be downgraded cleanly (rare — autogenerate produces both `upgrade` and `downgrade` but the latter is sometimes stripped during review), restore from a Postgres backup taken just before the deploy.

## Lingering NPM hot-fix (TEMPORARY — Keenan to persist)

The host nginx config is currently in a hand-edited state that will be wiped the next time someone clicks Save in the NPM admin UI for `songbird.kee-flix.com`. Keenan needs to set both via the UI so the changes persist:

1. **Forward Scheme = `http`** (was `https` by default — caused the `502 Bad Gateway` we hit during initial bring-up).
2. **Custom Nginx Configuration:** add `client_max_body_size 100m;` (so `/v1/import` multipart uploads above 1 MB don't 413).

Backup of the original NPM-generated config lives at `/home/keenan/netflix/nginx/data/nginx/proxy_host/3.conf.bak` on keebox.

> **Until Keenan saves these in the NPM UI, never click Save on the proxy host entry — it will overwrite the hand-edited `.conf` with NPM's default and break the site.**

## What's next (in order)

1. **Test harness** (Tier 1 from earlier audit): songbirdapi pytest CI gate, songbirdcore gdrive/youtube coverage, songbirdapi security unit tests, songbirdweb React component tests.
2. **CI deploy** per repo following `keebox-app-template`: build to GHCR, SSH + pull on keebox.
3. **Small UI polish** flagged during beta usage: dove counter / "X finished" grey text desync vs "done" chip, etc.

## Quick reference — common ops on keebox

| Thing | Command |
|---|---|
| Tail API logs | `docker compose logs -f --tail 100 songbirdapi` |
| Tail web logs | `docker compose logs -f --tail 100 songbirdweb` |
| Restart API only | `docker compose restart songbirdapi` |
| Open psql | `docker exec -it songbird-postgres psql -U $POSTGRES_USER -d $POSTGRES_DB` |
| Apply pending migrations | `docker compose run --rm songbirdapi alembic upgrade head` |
| Clean up dangling images | `docker image prune -f` |
| Check disk usage | `du -sh /mnt/jellydisk3/songbird/*` |

## Why we deploy this way (for now)

Manual beta deploy validates the full stack with real users before automating CI. ~567 enriched MP3 / M4A files were imported via the import UI for content. Once the test harness backlog is cleared and CI deploy lands, this runbook becomes a fallback for emergency rollbacks; routine pushes will be automated.
