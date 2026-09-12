"""Persists TMDb show/season/episode metadata locally so it isn't re-fetched every launch."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from plexlibrary.models.metadata import CachedShowMetadata, TvShowMetadata

_DB_FILE_NAME = "tmdb_cache.sqlite3"
_LEGACY_CACHE_FILE_NAME = "tmdb_cache.json"
_POSTER_DIR_NAME = "tmdb_posters"


class MetadataCacheService:
    """Reads/writes the on-disk TMDb metadata cache, keyed by Plex show id."""

    def __init__(self, config_dir: Path) -> None:
        self._db_file = config_dir / _DB_FILE_NAME
        self._legacy_cache_file = config_dir / _LEGACY_CACHE_FILE_NAME
        self._poster_dir = config_dir / _POSTER_DIR_NAME
        self._ensure_schema()
        self._migrate_legacy_cache()

    def get(self, plex_show_id: int) -> CachedShowMetadata | None:
        connection = self._connect()
        with connection:
            row = connection.execute(
                "SELECT metadata_json, fetched_at, seasons_detail_fetched FROM shows WHERE plex_show_id = ?",
                (plex_show_id,),
            ).fetchone()
        if row is None:
            return None
        metadata_json, fetched_at, seasons_detail_fetched = row
        return CachedShowMetadata(
            plex_show_id=plex_show_id,
            metadata=TvShowMetadata.model_validate_json(metadata_json),
            fetched_at=fetched_at,
            seasons_detail_fetched=bool(seasons_detail_fetched),
        )

    def save(self, entry: CachedShowMetadata) -> None:
        entry = entry.model_copy(update={"fetched_at": datetime.now(tz=UTC).isoformat()})
        connection = self._connect()
        with connection:
            connection.execute(
                """
                INSERT INTO shows (plex_show_id, metadata_json, fetched_at, seasons_detail_fetched)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(plex_show_id) DO UPDATE SET
                    metadata_json = excluded.metadata_json,
                    fetched_at = excluded.fetched_at,
                    seasons_detail_fetched = excluded.seasons_detail_fetched
                """,
                (
                    entry.plex_show_id,
                    entry.metadata.model_dump_json(),
                    entry.fetched_at,
                    int(entry.seasons_detail_fetched),
                ),
            )

    def poster_path(self, tmdb_id: int) -> Path:
        return self._poster_dir / f"{tmdb_id}.img"

    def load_poster_bytes(self, tmdb_id: int) -> bytes | None:
        path = self.poster_path(tmdb_id)
        if path.is_file():
            return path.read_bytes()
        return None

    def save_poster_bytes(self, tmdb_id: int, data: bytes) -> None:
        self._poster_dir.mkdir(parents=True, exist_ok=True)
        self.poster_path(tmdb_id).write_bytes(data)

    def _connect(self) -> sqlite3.Connection:
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self._db_file)

    def _ensure_schema(self) -> None:
        connection = self._connect()
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS shows (
                    plex_show_id INTEGER PRIMARY KEY,
                    metadata_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL DEFAULT '',
                    seasons_detail_fetched INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def _migrate_legacy_cache(self) -> None:
        """One-time import of the old tmdb_cache.json into the database, then rename it aside."""

        if not self._legacy_cache_file.is_file():
            return

        try:
            data = json.loads(self._legacy_cache_file.read_text(encoding="utf-8"))
            raw_entries: dict[str, object] = data.get("shows", {})
        except (OSError, json.JSONDecodeError, ValueError):
            raw_entries = {}

        connection = self._connect()
        with connection:
            for raw_entry in raw_entries.values():
                try:
                    cached = CachedShowMetadata.model_validate(raw_entry)
                except ValueError:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO shows (plex_show_id, metadata_json, fetched_at, seasons_detail_fetched)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        cached.plex_show_id,
                        cached.metadata.model_dump_json(),
                        cached.fetched_at,
                        int(cached.seasons_detail_fetched),
                    ),
                )

        self._legacy_cache_file.replace(self._legacy_cache_file.with_suffix(".json.migrated"))
