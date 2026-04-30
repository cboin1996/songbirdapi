"""Seed song_plays, song_downloads, and user_songs with dev data."""

import asyncio
import json
import os
import random
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DSN = "postgresql+asyncpg://songbirdapi:songbirdapi@localhost:5432/songbirdapi"
DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "downloads")

engine = create_async_engine(DSN, echo=False)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


def rand_dt(days_ago_max: int) -> datetime:
    offset = timedelta(seconds=random.randint(0, days_ago_max * 86400))
    return datetime.now(timezone.utc) - offset


async def seed():
    async with session_factory() as db:
        songs = (
            await db.execute(
                text("SELECT uuid FROM songs WHERE properties IS NOT NULL")
            )
        ).fetchall()
        users = (await db.execute(text("SELECT id FROM users"))).fetchall()

        if not songs:
            print("No songs found — download some songs first.")
            return
        if not users:
            print("No users found.")
            return

        song_ids = [r[0] for r in songs]
        user_ids = [r[0] for r in users]

        print(f"Seeding with {len(song_ids)} songs and {len(user_ids)} users...")

        plays = []
        downloads = []
        saves = []

        for song_id in song_ids:
            play_count = random.randint(1, 30)
            for _ in range(play_count):
                user_id = random.choice(user_ids)
                plays.append(
                    {
                        "id": str(uuid.uuid4()),
                        "song_id": song_id,
                        "user_id": user_id,
                        "played_at": rand_dt(30),
                    }
                )

            dl_count = random.randint(0, 10)
            for _ in range(dl_count):
                user_id = random.choice(user_ids)
                downloads.append(
                    {
                        "id": str(uuid.uuid4()),
                        "song_id": song_id,
                        "user_id": user_id,
                        "downloaded_at": rand_dt(30),
                    }
                )

            for user_id in user_ids:
                if random.random() > 0.4:
                    saves.append(
                        {
                            "user_id": user_id,
                            "song_id": song_id,
                            "added_at": rand_dt(60),
                            "last_position": 0.0,
                            "last_played_at": None,
                        }
                    )

        if plays:
            await db.execute(
                text("""
                    INSERT INTO song_plays (id, song_id, user_id, played_at)
                    VALUES (:id, :song_id, :user_id, :played_at)
                    ON CONFLICT DO NOTHING
                """),
                plays,
            )

        if downloads:
            await db.execute(
                text("""
                    INSERT INTO song_downloads (id, song_id, user_id, downloaded_at)
                    VALUES (:id, :song_id, :user_id, :downloaded_at)
                    ON CONFLICT DO NOTHING
                """),
                downloads,
            )

        if saves:
            await db.execute(
                text("""
                    INSERT INTO user_songs (user_id, song_id, added_at, last_position, last_played_at)
                    VALUES (:user_id, :song_id, :added_at, :last_position, :last_played_at)
                    ON CONFLICT DO NOTHING
                """),
                saves,
            )

        await db.commit()
        print(
            f"Inserted {len(plays)} plays, {len(downloads)} downloads, {len(saves)} library saves."
        )

        await seed_test_songs(db)

    await engine.dispose()


async def seed_test_songs(db):
    """Create dev-only test songs used by Playwright tests."""
    existing = (
        await db.execute(
            text("SELECT uuid FROM songs WHERE properties->>'trackName' = 'edit-me'")
        )
    ).fetchone()
    if existing:
        print(f"edit-me already exists ({existing[0]}), skipping.")
        return

    jolene = (
        await db.execute(
            text(
                "SELECT uuid, url, file_path, properties FROM songs WHERE properties->>'trackName' ILIKE '%jolene%' LIMIT 1"
            )
        )
    ).fetchone()
    if not jolene:
        print("Jolene not found — skipping edit-me creation.")
        return

    src_uuid, src_url, src_path, props_json = jolene
    props = json.loads(props_json) if isinstance(props_json, str) else props_json

    new_uuid = str(uuid.uuid4())
    dest_path = os.path.join(DOWNLOADS_DIR, f"{new_uuid}.mp3")
    shutil.copy2(src_path, dest_path)

    new_props = dict(props)
    new_props["trackName"] = "edit-me"

    await db.execute(
        text("""
        INSERT INTO songs (uuid, url, file_path, properties, parent_song_id, created_at)
        VALUES (:uuid, :url, :file_path, cast(:properties as jsonb), :parent_song_id, now())
    """),
        {
            "uuid": new_uuid,
            "url": src_url,
            "file_path": dest_path,
            "properties": json.dumps(new_props),
            "parent_song_id": src_uuid,
        },
    )

    cboin = (
        await db.execute(text("SELECT id FROM users WHERE username = 'cboin' LIMIT 1"))
    ).fetchone()
    if cboin:
        await db.execute(
            text("""
            INSERT INTO user_songs (user_id, song_id, added_at, last_position, last_played_at)
            VALUES (:user_id, :song_id, now(), 0, null) ON CONFLICT DO NOTHING
        """),
            {"user_id": cboin[0], "song_id": new_uuid},
        )

    await db.commit()
    print(f"Created edit-me ({new_uuid}), added to cboin's library.")


asyncio.run(seed())
