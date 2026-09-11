"""Looks up TV show metadata from TMDb (The Movie Database)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from plexlibrary.models.metadata import TvShowMetadata
from plexlibrary.services.settings_service import SettingsService

TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w342"
_REQUEST_TIMEOUT = 15


class MetadataError(RuntimeError):
    """Raised when TV show metadata could not be retrieved from TMDb."""


class TmdbMetadataService:
    """Fetches TV show metadata and poster art from TMDb using the configured API key."""

    def __init__(self, settings_service: SettingsService) -> None:
        self._settings_service = settings_service

    def fetch_show_metadata(self, name: str, year: int | None = None) -> TvShowMetadata:
        """Search TMDb for `name` (optionally narrowed by first-air year) and return the best match."""

        api_key = self._settings_service.load_tmdb_api_key().strip()
        if not api_key:
            raise MetadataError("No TMDb API key is configured. Add one in Settings.")

        tmdb_id = self._search_show_id(api_key, name, year)
        if tmdb_id is None:
            raise MetadataError(f'No TMDb match found for "{name}".')
        return self._get_show_details(api_key, tmdb_id)

    def fetch_poster_bytes(self, poster_url: str) -> bytes:
        """Download poster art. Raises `MetadataError` on failure."""

        request = urllib.request.Request(poster_url)
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
                return response.read()
        except urllib.error.URLError as exc:
            raise MetadataError(f"Failed to download poster image: {exc}") from exc

    def _search_show_id(self, api_key: str, name: str, year: int | None) -> int | None:
        params = {"api_key": api_key, "query": name}
        if year is not None:
            params["first_air_date_year"] = str(year)
        data = self._get_json("/search/tv", params)
        results = data.get("results") or []
        if not results:
            return None
        return int(results[0]["id"])

    def _get_show_details(self, api_key: str, tmdb_id: int) -> TvShowMetadata:
        data = self._get_json(f"/tv/{tmdb_id}", {"api_key": api_key})
        poster_path = data.get("poster_path") or ""
        return TvShowMetadata(
            tmdb_id=int(data["id"]),
            name=str(data.get("name") or ""),
            overview=str(data.get("overview") or ""),
            first_air_date=str(data.get("first_air_date") or ""),
            status=str(data.get("status") or ""),
            vote_average=data.get("vote_average"),
            number_of_seasons=data.get("number_of_seasons"),
            number_of_episodes=data.get("number_of_episodes"),
            genres=[genre["name"] for genre in data.get("genres") or []],
            networks=[network["name"] for network in data.get("networks") or []],
            poster_url=f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else "",
        )

    def _get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{TMDB_API_BASE_URL}{path}?{query}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise MetadataError("TMDb rejected the configured API key (401 Unauthorized).") from exc
            if exc.code == 404:
                raise MetadataError("TMDb show not found (404).") from exc
            raise MetadataError(f"TMDb request failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise MetadataError(f"Failed to reach TMDb: {exc.reason}") from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MetadataError("TMDb returned an invalid response.") from exc
