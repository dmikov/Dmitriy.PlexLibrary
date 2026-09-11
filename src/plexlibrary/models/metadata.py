"""Models for TV show metadata fetched from TMDb."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
