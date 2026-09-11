"""Retrieves a copy of the Plex database file over whichever transport is configured."""

from __future__ import annotations

import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path

import smbclient

from plexlibrary.models.connection import (
    ConnectionSettings,
    LocalConnectionSettings,
    PlexDiagnosticsConnectionSettings,
    SmbConnectionSettings,
)

LIBRARY_DB_FILENAME = "com.plexapp.plugins.library.db"
DIAGNOSTICS_LIBRARY_DB_PREFIX = "databaseBackup.db"


class DatabaseDownloadError(RuntimeError):
    """Raised when the Plex database could not be retrieved."""


class DatabaseDownloader(ABC):
    """Fetches a Plex database file and stores it locally."""

    @abstractmethod
    def download(self, destination: Path) -> Path:
        """Copy the database to `destination`, creating parent directories as needed."""
        raise NotImplementedError


class LocalDatabaseDownloader(DatabaseDownloader):
    """Copies a database that is already reachable through the local filesystem."""

    def __init__(self, settings: LocalConnectionSettings) -> None:
        self._settings = settings

    def download(self, destination: Path) -> Path:
        source = Path(self._settings.database_path)
        if not source.is_file():
            raise DatabaseDownloadError(f"Database file not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source, destination)
        except OSError as exc:
            raise DatabaseDownloadError(f"Failed to copy {source}: {exc}") from exc
        return destination


class SmbDatabaseDownloader(DatabaseDownloader):
    """Downloads a database file from an SMB/CIFS network share."""

    def __init__(self, settings: SmbConnectionSettings, password: str) -> None:
        self._settings = settings
        self._password = password

    def download(self, destination: Path) -> Path:
        settings = self._settings
        remote_path = "\\\\{server}\\{share}\\{path}".format(
            server=settings.server,
            share=settings.share,
            path=settings.database_path.replace("/", "\\").lstrip("\\"),
        )
        try:
            smbclient.register_session(
                settings.server,
                username=settings.username or None,
                password=self._password or None,
                port=settings.port,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            with smbclient.open_file(remote_path, mode="rb") as remote_file:
                with destination.open("wb") as local_file:
                    shutil.copyfileobj(remote_file, local_file)
        except DatabaseDownloadError:
            raise
        except Exception as exc:
            raise DatabaseDownloadError(f"Failed to download {remote_path}: {exc}") from exc
        finally:
            smbclient.delete_session(settings.server, port=settings.port)
        return destination


class PlexDiagnosticsDatabaseDownloader(DatabaseDownloader):
    """Downloads Plex databases via the diagnostics API and extracts the library DB from the ZIP."""

    def __init__(self, settings: PlexDiagnosticsConnectionSettings, token: str) -> None:
        self._settings = settings
        self._token = token

    def download(self, destination: Path) -> Path:
        settings = self._settings
        if not settings.host.strip():
            raise DatabaseDownloadError("Plex server host is required.")
        if not self._token.strip():
            raise DatabaseDownloadError("X-Plex-Token is required.")

        query = urllib.parse.urlencode({"X-Plex-Token": self._token})
        url = f"{settings.base_url}/diagnostics/databases/?{query}"
        request = urllib.request.Request(url)

        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                zip_bytes = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise DatabaseDownloadError("Unauthorized: invalid or missing X-Plex-Token.") from exc
            raise DatabaseDownloadError(
                f"Failed to download diagnostics archive from {settings.base_url}: HTTP {exc.code}"
            ) from exc
        except urllib.error.URLError as exc:
            raise DatabaseDownloadError(
                f"Failed to connect to Plex server at {settings.base_url}: {exc.reason}"
            ) from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = Path(temp_dir) / "plex-databases.zip"
                zip_path.write_bytes(zip_bytes)
                db_member = _find_library_db_member(zip_path)
                if db_member is None:
                    raise DatabaseDownloadError(
                        "Library database file was not found in the diagnostics archive "
                        f"(expected {LIBRARY_DB_FILENAME} or {DIAGNOSTICS_LIBRARY_DB_PREFIX}*)."
                    )
                with zipfile.ZipFile(zip_path) as archive:
                    with archive.open(db_member) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
        except zipfile.BadZipFile as exc:
            raise DatabaseDownloadError("Diagnostics response was not a valid ZIP archive.") from exc
        except OSError as exc:
            raise DatabaseDownloadError(f"Failed to write {destination}: {exc}") from exc

        return destination


def _find_library_db_member(zip_path: Path) -> str | None:
    with zipfile.ZipFile(zip_path) as archive:
        file_members = [member for member in archive.namelist() if not member.endswith("/")]

        for member in file_members:
            if Path(member).name == LIBRARY_DB_FILENAME:
                return member

        backup_members = [
            member
            for member in file_members
            if Path(member).name.startswith(DIAGNOSTICS_LIBRARY_DB_PREFIX)
        ]
        if not backup_members:
            return None
        if len(backup_members) == 1:
            return backup_members[0]

        # Plex may include multiple database backups; the main library DB is usually the largest.
        return max(backup_members, key=lambda member: archive.getinfo(member).file_size)


def create_downloader(settings: ConnectionSettings, password: str) -> DatabaseDownloader:
    """Build the `DatabaseDownloader` matching the given connection settings."""

    if isinstance(settings, LocalConnectionSettings):
        return LocalDatabaseDownloader(settings)
    if isinstance(settings, SmbConnectionSettings):
        return SmbDatabaseDownloader(settings, password)
    if isinstance(settings, PlexDiagnosticsConnectionSettings):
        return PlexDiagnosticsDatabaseDownloader(settings, password)
    raise ValueError(f"Unsupported connection settings: {settings!r}")
