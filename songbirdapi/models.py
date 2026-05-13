import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    cast,
    Date,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class EditJobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"
    duplicate = "duplicate"


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    admin = "admin"
    user = "user"


class RepeatMode(str, enum.Enum):
    off = "off"
    one = "one"
    all = "all"


class AudioFormat(str, enum.Enum):
    mp3 = "mp3"
    m4a = "m4a"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role), nullable=False, server_default=Role.user.value
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class Song(Base):
    __tablename__ = "songs"

    uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    artwork_thumb: Mapped[str | None] = mapped_column(Text, nullable=True)
    artwork_full: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_song_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="SET NULL"), nullable=True
    )
    root_song_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="SET NULL"), nullable=True
    )
    owner_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    __table_args__ = (
        Index("idx_songs_url", "url"),
        Index("idx_songs_props", "properties", postgresql_using="gin"),
    )


class UserSong(Base):
    __tablename__ = "user_songs"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    song_id: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    last_position: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    last_played_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SongPlay(Base):
    __tablename__ = "song_plays"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    song_id: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    __table_args__ = (
        Index("idx_song_plays_song_id", "song_id"),
        Index("idx_song_plays_played_at", "played_at"),
    )


class UserPlayerState(Base):
    __tablename__ = "user_player_state"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    shuffle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    repeat: Mapped[RepeatMode] = mapped_column(
        SAEnum(RepeatMode), nullable=False, server_default=RepeatMode.off.value
    )
    queue: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    queue_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="-1"
    )
    shuffle_order: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    play_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shuffle_seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shuffle_position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    manual_next: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    current_song_uuid: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    queue_sources: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class SongDownload(Base):
    __tablename__ = "song_downloads"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    song_id: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )

    __table_args__ = (
        Index("idx_song_downloads_song_id", "song_id"),
        Index("idx_song_downloads_downloaded_at", "downloaded_at"),
    )


class SongShareToken(Base):
    __tablename__ = "song_share_tokens"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    song_id: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class EditJob(Base):
    __tablename__ = "edit_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_song_id: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[EditJobStatus] = mapped_column(
        SAEnum(EditJobStatus),
        nullable=False,
        server_default=EditJobStatus.pending.value,
    )
    result_song_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EditJobStatus] = mapped_column(
        SAEnum(EditJobStatus),
        nullable=False,
        server_default=EditJobStatus.pending.value,
    )
    song_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_of: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SongEditDraft(Base):
    __tablename__ = "song_edit_drafts"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    song_id: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), primary_key=True
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class Playlist(Base):
    __tablename__ = "playlists"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PlaylistSong(Base):
    __tablename__ = "playlist_songs"
    playlist_id: Mapped[str] = mapped_column(
        Text, ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True
    )
    song_uuid: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class UserOfflineSong(Base):
    __tablename__ = "user_offline_songs"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    song_id: Mapped[str] = mapped_column(
        Text, ForeignKey("songs.uuid", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    audio_format: Mapped[AudioFormat] = mapped_column(
        SAEnum(AudioFormat), nullable=False, server_default=AudioFormat.mp3.value
    )


class ErrorLog(Base):
    __tablename__ = "error_logs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()"
    )
    level: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("idx_error_logs_timestamp", "timestamp"),)
