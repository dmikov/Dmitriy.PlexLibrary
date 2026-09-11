"""Models for TV show metadata fetched from TMDb."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TvEpisodeMetadata(BaseModel):
    """Metadata for one episode, as returned by TMDb's `/tv/{id}/season/{n}` endpoint."""

    episode_number: int | None = None
    name: str = ""
    air_date: str = ""
    overview: str = ""
    vote_average: float | None = None


class TvSeasonMetadata(BaseModel):
    """Metadata for one season, as returned within TMDb's `/tv/{id}` response and detail endpoint."""

    season_number: int | None = None
    name: str = ""
    air_date: str = ""
    episode_count: int = 0
    overview: str = ""
    poster_path: str = ""
    episodes: list[TvEpisodeMetadata] = Field(default_factory=list)


class TvShowMetadata(BaseModel):
    """Metadata for one TV series, as returned by TMDb's `/tv/{id}` endpoint."""

    tmdb_id: int
    name: str
    overview: str = ""
    first_air_date: str = ""
    status: str = ""
    vote_average: float | None = None
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None
    genres: list[str] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    poster_url: str = ""
    seasons: list[TvSeasonMetadata] = Field(default_factory=list)

    @property
    def season_numbers(self) -> list[int]:
        """The season numbers TMDb reports, in order (e.g. `[0, 1, 2]`, 0 being specials)."""
        return sorted(season.season_number for season in self.seasons if season.season_number is not None)


class CachedShowMetadata(BaseModel):
    """One cached TMDb lookup, keyed by the Plex show it was fetched for."""

    plex_show_id: int
    metadata: TvShowMetadata
    fetched_at: str = ""
    seasons_detail_fetched: bool = False
