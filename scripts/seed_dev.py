"""Seed song_plays, song_downloads, and user_songs with dev data."""
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DSN = "postgresql+asyncpg://songbirdapi:songbirdapi@localhost:5432/songbirdapi"

engine = create_async_engine(DSN, echo=False)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


def rand_dt(days_ago_max: int) -> datetime:
    offset = timedelta(
        seconds=random.randint(0, days_ago_max * 86400)
    )
    return datetime.now(timezone.utc) - offset


async def seed():
    async with session_factory() as db:
        songs = (await db.execute(text("SELECT uuid FROM songs WHERE properties IS NOT NULL"))).fetchall()
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
                plays.append({
                    "id": str(uuid.uuid4()),
                    "song_id": song_id,
                    "user_id": user_id,
                    "played_at": rand_dt(30),
                })

            dl_count = random.randint(0, 10)
            for _ in range(dl_count):
                user_id = random.choice(user_ids)
                downloads.append({
                    "id": str(uuid.uuid4()),
                    "song_id": song_id,
                    "user_id": user_id,
                    "downloaded_at": rand_dt(30),
                })

            for user_id in user_ids:
                if random.random() > 0.4:
                    saves.append({
                        "user_id": user_id,
                        "song_id": song_id,
                        "added_at": rand_dt(60),
                        "last_position": 0.0,
                        "last_played_at": None,
                    })

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
        print(f"Inserted {len(plays)} plays, {len(downloads)} downloads, {len(saves)} library saves.")

    await engine.dispose()


asyncio.run(seed())
