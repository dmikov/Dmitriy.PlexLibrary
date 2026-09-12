"""Ensures a fresh local Plex database file and reads library sections from it."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from plexlibrary.models.library import LibrarySection
from plexlibrary.models.tv import (
    PLEX_METADATA_TYPE_EPISODE,
    PLEX_METADATA_TYPE_SEASON,
    PLEX_METADATA_TYPE_SHOW,
    TvEpisodeRecord,
    TvSeasonRecord,
    TvShowSummary,
)
from plexlibrary.services.database_downloader import create_downloader
from plexlibrary.services.settings_service import SettingsService

DEFAULT_MAX_AGE = timedelta(days=1)

_DOWNLOADED_DB_FILE_NAME = "downloaded_library.db"


class LibraryDbError(RuntimeError):
    """Raised when the local Plex database could not be prepared or read."""


class LibraryDbService:
    """Downloads or reuses a local Plex database and queries library metadata from it."""

    def __init__(
        self,
        settings_service: SettingsService,
        *,
        max_age: timedelta = DEFAULT_MAX_AGE,
    ) -> None:
        self._settings_service = settings_service
        self._max_age = max_age

    @property
    def max_age(self) -> timedelta:
        return self._max_age

    @property
    def database_path(self) -> Path:
        """Where the downloaded database is stored, alongside settings and the TMDb cache."""
        return self._settings_service.config_dir / _DOWNLOADED_DB_FILE_NAME

    def ensure_local_database(self, *, force: bool = False) -> Path:
        """Return a local database path, downloading again when missing, stale, or `force` is set."""

        app_settings = self._settings_service.load()
        if app_settings.connection is None:
            raise LibraryDbError("Configure a connection in Settings before loading libraries.")

        destination = self.database_path
        if not force and destination.is_file() and self._is_fresh(destination):
            return destination

        password = self._settings_service.load_password(app_settings.connection)
        downloader = create_downloader(app_settings.connection, password)
        return downloader.download(destination)

    def list_libraries(self, db_path: Path | None = None) -> list[LibrarySection]:
        """Read Plex library sections from the local database file."""

        database_path = db_path or self.ensure_local_database()
        if not database_path.is_file():
            raise LibraryDbError(f"Database file not found: {database_path}")

        try:
            connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            with connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(library_sections)").fetchall()
                }
                if "name" not in columns or "id" not in columns:
                    raise LibraryDbError("Database is missing the expected library_sections table.")

                select_columns = ["id", "name"]
                if "section_type" in columns:
                    select_columns.append("section_type")

                query = (
                    f"SELECT {', '.join(select_columns)} "
                    "FROM library_sections "
                    "ORDER BY name COLLATE NOCASE"
                )
                rows = connection.execute(query).fetchall()
        except sqlite3.Error as exc:
            raise LibraryDbError(f"Failed to read libraries from {database_path}: {exc}") from exc

        libraries: list[LibrarySection] = []
        for row in rows:
            section_type: int | None = None
            if "section_type" in row.keys() and row["section_type"] is not None:
                section_type = int(row["section_type"])
            libraries.append(
                LibrarySection(
                    id=int(row["id"]),
                    name=str(row["name"]),
                    section_type=section_type,
                )
            )
        return libraries

    def list_tv_shows(
        self,
        library_section_id: int,
        db_path: Path,
        *,
        sort_by: str = "name",
        sort_desc: bool = False,
    ) -> list[TvShowSummary]:
        """Return TV series in a library section, sorted for display."""

        if not db_path.is_file():
            raise LibraryDbError(f"Database file not found: {db_path}")

        sort_columns = {
            "name": "shows.title_sort COLLATE NOCASE",
            "year": "shows.year",
            "seasons": "season_count",
        }
        order_column = sort_columns.get(sort_by, sort_columns["name"])
        direction = "DESC" if sort_desc else "ASC"

        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            with connection:
                metadata_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(metadata_items)").fetchall()
                }
                if "title_sort" not in metadata_columns:
                    sort_columns["name"] = "shows.title COLLATE NOCASE"
                    if sort_by == "name":
                        order_column = sort_columns["name"]

                query = f"""
                    SELECT
                        shows.id,
                        shows.title,
                        shows.year,
                        (
                            SELECT COUNT(*)
                            FROM metadata_items seasons
                            WHERE seasons.parent_id = shows.id
                              AND seasons.metadata_type = {PLEX_METADATA_TYPE_SEASON}
                        ) AS season_count
                    FROM metadata_items shows
                    WHERE shows.library_section_id = ?
                      AND shows.metadata_type = {PLEX_METADATA_TYPE_SHOW}
                      AND (shows.parent_id IS NULL OR shows.parent_id = 0)
                    ORDER BY {order_column} {direction}, shows.title COLLATE NOCASE ASC
                """
                rows = connection.execute(query, (library_section_id,)).fetchall()
        except sqlite3.Error as exc:
            raise LibraryDbError(f"Failed to read TV shows from {db_path}: {exc}") from exc

        return [
            TvShowSummary(
                id=int(row["id"]),
                name=str(row["title"]),
                year=int(row["year"]) if row["year"] is not None else None,
                season_count=int(row["season_count"] or 0),
            )
            for row in rows
        ]

    def get_show_seasons_and_episodes(self, show_id: int, db_path: Path) -> list[TvSeasonRecord]:
        """Return seasons and episodes for one TV series."""

        if not db_path.is_file():
            raise LibraryDbError(f"Database file not found: {db_path}")

        query = f"""
            SELECT
                seasons.id AS season_id,
                seasons.[index] AS season_number,
                episodes.id AS episode_id,
                episodes.[index] AS episode_number,
                episodes.title AS episode_title,
                media.width AS width,
                media.height AS height,
                media.size AS media_size,
                parts.file AS file_path
            FROM metadata_items seasons
            LEFT JOIN metadata_items episodes
              ON episodes.parent_id = seasons.id
             AND episodes.metadata_type = {PLEX_METADATA_TYPE_EPISODE}
            LEFT JOIN media_items media
              ON media.metadata_item_id = episodes.id
            LEFT JOIN media_parts parts
              ON parts.media_item_id = media.id
            WHERE seasons.parent_id = ?
              AND seasons.metadata_type = {PLEX_METADATA_TYPE_SEASON}
            ORDER BY seasons.[index] ASC, episodes.[index] ASC
        """

        try:
            connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            with connection:
                rows = connection.execute(query, (show_id,)).fetchall()
        except sqlite3.Error as exc:
            raise LibraryDbError(f"Failed to read seasons for show {show_id}: {exc}") from exc

        seasons: dict[int, TvSeasonRecord] = {}
        for row in rows:
            season_id = int(row["season_id"])
            if season_id not in seasons:
                seasons[season_id] = TvSeasonRecord(
                    id=season_id,
                    season_number=int(row["season_number"]) if row["season_number"] is not None else None,
                    episodes=[],
                )
            if row["episode_id"] is None:
                continue
            seasons[season_id].episodes.append(
                TvEpisodeRecord(
                    id=int(row["episode_id"]),
                    episode_number=int(row["episode_number"]) if row["episode_number"] is not None else None,
                    title=str(row["episode_title"] or ""),
                    resolution=_format_resolution(row["width"], row["height"]),
                    filename=_format_filename(row["file_path"]),
                    size=_format_size(row["media_size"]),
                )
            )

        return sorted(
            seasons.values(),
            key=lambda season: season.season_number if season.season_number is not None else -1,
        )

    def _is_fresh(self, path: Path) -> bool:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        return datetime.now(tz=UTC) - modified_at < self._max_age


def _format_resolution(width: object, height: object) -> str:
    if width is None or height is None:
        return ""
    try:
        return f"{int(width)}x{int(height)}"
    except (TypeError, ValueError):
        return ""


def _format_filename(file_path: object) -> str:
    """Basename of a Plex media part's file path, whether it uses `/` or `\\` separators."""
    if not file_path:
        return ""
    return str(file_path).replace("\\", "/").rsplit("/", 1)[-1]


def _format_size(size_bytes: object) -> str:
    """Human-readable file size, e.g. `4.05 GB`."""
    try:
        size = float(size_bytes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return ""
