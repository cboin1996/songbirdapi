import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    admin = "admin"
    user = "user"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(SAEnum(Role), nullable=False, server_default=Role.user.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class Song(Base):
    __tablename__ = "songs"

    uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_songs_url", "url"),
        Index("idx_songs_props", "properties", postgresql_using="gin"),
    )


class UserSong(Base):
    __tablename__ = "user_songs"

    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    song_id: Mapped[str] = mapped_column(Text, ForeignKey("songs.uuid", ondelete="CASCADE"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    last_position: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SongPlay(Base):
    __tablename__ = "song_plays"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    song_id: Mapped[str] = mapped_column(Text, ForeignKey("songs.uuid", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_song_plays_song_id", "song_id"),
        Index("idx_song_plays_played_at", "played_at"),
    )


class SongDownload(Base):
    __tablename__ = "song_downloads"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    song_id: Mapped[str] = mapped_column(Text, ForeignKey("songs.uuid", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    __table_args__ = (
        Index("idx_song_downloads_song_id", "song_id"),
        Index("idx_song_downloads_downloaded_at", "downloaded_at"),
    )
