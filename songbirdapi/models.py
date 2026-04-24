from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Song(Base):
    __tablename__ = "songs"

    uuid: Mapped[str] = mapped_column(Text, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
    )

    __table_args__ = (
        Index("idx_songs_url", "url"),
        Index("idx_songs_props", "properties", postgresql_using="gin"),
    )
