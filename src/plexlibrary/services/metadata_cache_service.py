"""Persists TMDb show/season/episode metadata locally so it isn't re-fetched every launch."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from plexlibrary.models.metadata import CachedShowMetadata

_CACHE_FILE_NAME = "tmdb_cache.json"
_POSTER_DIR_NAME = "tmdb_posters"


class _CacheFile(BaseModel):
    shows: dict[str, CachedShowMetadata] = Field(default_factory=dict)


class MetadataCacheService:
    """Reads/writes the on-disk TMDb metadata cache, keyed by Plex show id."""

    def __init__(self, config_dir: Path) -> None:
        self._cache_file = config_dir / _CACHE_FILE_NAME
        self._poster_dir = config_dir / _POSTER_DIR_NAME

    def get(self, plex_show_id: int) -> CachedShowMetadata | None:
        return self._load().shows.get(str(plex_show_id))

    def save(self, entry: CachedShowMetadata) -> None:
        cache = self._load()
        entry = entry.model_copy(update={"fetched_at": datetime.now(tz=UTC).isoformat()})
        cache.shows[str(entry.plex_show_id)] = entry
        self._save(cache)

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

    def _load(self) -> _CacheFile:
        if not self._cache_file.is_file():
            return _CacheFile()
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            return _CacheFile.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return _CacheFile()

    def _save(self, cache: _CacheFile) -> None:
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = cache.model_dump_json(indent=2)
        temp_file = self._cache_file.with_suffix(".json.tmp")
        temp_file.write_text(payload, encoding="utf-8")
        temp_file.replace(self._cache_file)
