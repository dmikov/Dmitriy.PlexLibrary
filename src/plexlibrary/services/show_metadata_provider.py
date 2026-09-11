"""Coordinates TMDb lookups with the on-disk metadata cache.

Saved metadata is used unless a refresh is explicitly requested; when nothing is saved yet,
it is fetched from TMDb and saved.
"""

from __future__ import annotations

from plexlibrary.models.metadata import CachedShowMetadata, TvShowMetadata
from plexlibrary.services.metadata_cache_service import MetadataCacheService
from plexlibrary.services.metadata_service import MetadataError, TmdbMetadataService


class ShowMetadataProvider:
    """Returns cached TMDb metadata when available, otherwise fetches and caches it."""

    def __init__(
        self,
        metadata_service: TmdbMetadataService,
        cache_service: MetadataCacheService,
    ) -> None:
        self._metadata_service = metadata_service
        self._cache_service = cache_service

    def has_api_key(self) -> bool:
        return self._metadata_service.has_api_key()

    def get_season_summary(self, plex_show_id: int, name: str, year: int | None) -> TvShowMetadata:
        """Season count/sequence for the show grid: cached if present, else fetched and cached."""

        cached = self._cache_service.get(plex_show_id)
        if cached is not None:
            return cached.metadata

        metadata = self._metadata_service.fetch_show_summary(name, year)
        self._cache_service.save(
            CachedShowMetadata(
                plex_show_id=plex_show_id,
                metadata=metadata,
                seasons_detail_fetched=False,
            )
        )
        return metadata

    def get_full_metadata(
        self,
        plex_show_id: int,
        name: str,
        year: int | None,
        *,
        force_refresh: bool = False,
    ) -> TvShowMetadata:
        """Full metadata incl. episodes: cached if already fetched in full, else fetched and cached."""

        cached = self._cache_service.get(plex_show_id)
        if not force_refresh and cached is not None and cached.seasons_detail_fetched:
            return cached.metadata

        metadata = self._metadata_service.fetch_show_full(name, year)
        self._cache_service.save(
            CachedShowMetadata(
                plex_show_id=plex_show_id,
                metadata=metadata,
                seasons_detail_fetched=True,
            )
        )
        return metadata

    def poster_bytes(self, metadata: TvShowMetadata, *, force_refresh: bool = False) -> bytes | None:
        """Poster art for `metadata`: cached on disk if present, else downloaded and cached."""

        if not metadata.poster_url:
            return None
        if not force_refresh:
            cached_poster = self._cache_service.load_poster_bytes(metadata.tmdb_id)
            if cached_poster is not None:
                return cached_poster
        try:
            data = self._metadata_service.fetch_poster_bytes(metadata.poster_url)
        except MetadataError:
            return None
        self._cache_service.save_poster_bytes(metadata.tmdb_id, data)
        return data

    def cached_poster_bytes(self, metadata: TvShowMetadata) -> bytes | None:
        """Poster art already on disk for `metadata`, without triggering a network fetch."""

        if not metadata.poster_url:
            return None
        return self._cache_service.load_poster_bytes(metadata.tmdb_id)
