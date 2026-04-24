"""
Migrate song data from Redis to PostgreSQL.

Usage:
    uv run python scripts/migrate_redis_to_postgres.py [--dry-run] [options]

All connection params can also be set via environment variables.
"""

import argparse
import asyncio
import json
import os

import asyncpg
import redis.asyncio as aioredis


async def migrate(
    dry_run: bool,
    redis_host: str,
    redis_port: int,
    pg_host: str,
    pg_port: int,
    pg_db: str,
    pg_user: str,
    pg_password: str,
):
    r = aioredis.Redis(host=redis_host, port=redis_port, decode_responses=True)

    if not dry_run:
        pg = await asyncpg.connect(
            host=pg_host, port=pg_port, database=pg_db, user=pg_user, password=pg_password,
        )

    keys = await r.keys("properties:*")
    print(f"Found {len(keys)} songs in Redis")

    inserted = 0
    skipped = 0
    errors = 0

    for key in keys:
        uuid = key.removeprefix("properties:")
        try:
            raw = await r.json().get(key)  # type: ignore
            if raw is None:
                print(f"  WARN: no data for {key}, skipping")
                skipped += 1
                continue

            url = raw.get("url", "")
            file_path = raw.get("file_path", "")
            properties = raw.get("properties")

            if dry_run:
                print(f"  DRY-RUN: would insert uuid={uuid} url={url}")
                inserted += 1
                continue

            await pg.execute(
                """
                INSERT INTO songs (uuid, url, file_path, properties, created_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (uuid) DO UPDATE
                    SET url = EXCLUDED.url,
                        file_path = EXCLUDED.file_path,
                        properties = EXCLUDED.properties
                """,
                uuid,
                url,
                file_path,
                json.dumps(properties) if properties else None,
            )
            print(f"  OK: {uuid} — {url}")
            inserted += 1

        except Exception as e:
            print(f"  ERROR: {key} — {e}")
            errors += 1

    await r.aclose()
    if not dry_run:
        await pg.close()

    print(f"\nDone. inserted={inserted} skipped={skipped} errors={errors}")
    if dry_run:
        print("(dry-run — no data was written)")


def main():
    parser = argparse.ArgumentParser(description="Migrate Redis → PostgreSQL")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--pg-host", default=os.getenv("POSTGRES_HOST", "localhost"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    parser.add_argument("--pg-db", default=os.getenv("POSTGRES_DB", "songbirdapi"))
    parser.add_argument("--pg-user", default=os.getenv("POSTGRES_USER", "songbirdapi"))
    parser.add_argument("--pg-password", default=os.getenv("POSTGRES_PASSWORD", ""))
    args = parser.parse_args()

    asyncio.run(migrate(
        args.dry_run,
        args.redis_host, args.redis_port,
        args.pg_host, args.pg_port, args.pg_db, args.pg_user, args.pg_password,
    ))


if __name__ == "__main__":
    main()
