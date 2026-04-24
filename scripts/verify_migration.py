"""
Verify Redis → PostgreSQL migration integrity.

For every properties:* key in Redis, checks that:
  - The UUID exists in Postgres
  - The url matches
  - The properties match (if present)

Usage:
    uv run python scripts/verify_migration.py [options]
"""

import argparse
import asyncio
import json
import os

import asyncpg
import redis.asyncio as aioredis


async def verify(
    redis_host: str,
    redis_port: int,
    pg_host: str,
    pg_port: int,
    pg_db: str,
    pg_user: str,
    pg_password: str,
):
    r = aioredis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    pg = await asyncpg.connect(
        host=pg_host, port=pg_port, database=pg_db, user=pg_user, password=pg_password,
    )

    redis_keys = await r.keys("properties:*")
    pg_rows = await pg.fetch("SELECT uuid, url, properties FROM songs")

    pg_by_uuid = {row["uuid"]: row for row in pg_rows}

    print(f"Redis songs : {len(redis_keys)}")
    print(f"Postgres rows: {len(pg_rows)}")

    passed = 0
    failed = 0

    for key in redis_keys:
        uuid = key.removeprefix("properties:")
        raw = await r.json().get(key)  # type: ignore

        if raw is None:
            print(f"  SKIP {uuid}: no data in Redis")
            continue

        pg_row = pg_by_uuid.get(uuid)
        if pg_row is None:
            print(f"  FAIL {uuid}: missing from Postgres")
            failed += 1
            continue

        if raw.get("url") != pg_row["url"]:
            print(f"  FAIL {uuid}: url mismatch — redis={raw.get('url')} pg={pg_row['url']}")
            failed += 1
            continue

        redis_props = raw.get("properties")
        pg_props = json.loads(pg_row["properties"]) if pg_row["properties"] else None
        if redis_props != pg_props:
            print(f"  FAIL {uuid}: properties mismatch")
            print(f"    redis: {json.dumps(redis_props)[:120]}")
            print(f"    pg:    {json.dumps(pg_props)[:120]}")
            failed += 1
            continue

        print(f"  OK   {uuid} — {pg_row['url']}")
        passed += 1

    # check for orphans in postgres not in redis
    redis_uuids = {k.removeprefix("properties:") for k in redis_keys}
    orphans = [row["uuid"] for row in pg_rows if row["uuid"] not in redis_uuids]
    if orphans:
        print(f"\n  WARN: {len(orphans)} rows in Postgres not found in Redis: {orphans}")

    await r.aclose()
    await pg.close()

    print(f"\nResult: {passed} passed, {failed} failed")
    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Verify Redis → Postgres migration")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--pg-host", default=os.getenv("POSTGRES_HOST", "localhost"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    parser.add_argument("--pg-db", default=os.getenv("POSTGRES_DB", "songbirdapi"))
    parser.add_argument("--pg-user", default=os.getenv("POSTGRES_USER", "songbirdapi"))
    parser.add_argument("--pg-password", default=os.getenv("POSTGRES_PASSWORD", ""))
    args = parser.parse_args()

    ok = asyncio.run(verify(
        args.redis_host, args.redis_port,
        args.pg_host, args.pg_port, args.pg_db, args.pg_user, args.pg_password,
    ))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
