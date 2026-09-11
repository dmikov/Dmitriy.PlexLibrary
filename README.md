# PlexLibrary

A desktop app (PySide6) for browsing your Plex TV library from a local copy of the
Plex `com.plexapp.plugins.library.db` database — reachable over a local path, SMB,
or the Plex diagnostics API — with optional TMDb metadata (overview, rating,
genres, poster) shown for the show you're currently inspecting.

## Setup

```bash
uv sync
uv run plexlibrary
```

## Configuring your Plex database connection

Open **Settings** (the gear icon in the toolbar) and choose how to reach your Plex
database file: a local/mounted path, an SMB share, or the Plex diagnostics API.
Credentials are stored in your OS keyring, never in the plain-text settings file.

## TV show metadata (TMDb)

When you expand a show in the library grid, PlexLibrary looks it up on
[TMDb](https://www.themoviedb.org/) (The Movie Database) and shows its overview,
rating, genres, network, and poster. This is optional — without an API key the
grid still works, you just won't see the metadata panel or the TMDb columns below.

### Season count check

With an API key configured, the show grid also gets a **TMDb Seasons** column next
to Plex's own **Seasons** column. If the two numbers disagree, the whole row's text
turns orange to flag the mismatch — a quick way to spot shows where your Plex
library is missing (or has extra) seasons compared to TMDb. Hovering the TMDb
Seasons cell shows the actual season sequence TMDb reports (e.g. specials as
season `0`). Expanding a show applies the same orange-text treatment per season
when its Plex and TMDb episode counts disagree — and adds a row (in red) for any
season TMDb knows about that has no matching season in your Plex library at all.
A missing season still shows TMDb's episode count, just nothing in the Plex
episode-count column — there's nothing there to report.

Expanding a season goes one level further: the episode grid shows each episode's
filename, resolution, and file size on disk, and adds a row (in red) for any
episode TMDb knows about that isn't in your Plex library — a quick way to spot
gaps. Missing episodes obviously have no filename, resolution, or size to show. A
missing season's episode grid is red across the board, since none of its
episodes are in Plex either.

Click the **⟳** icon at the start of a row to force a hard refresh of that show's
TMDb data, bypassing the cache described below.

### Local metadata caching

TMDb data (show details, season/episode lists, and poster art) is cached locally
after the first lookup and reused on later runs instead of being re-fetched — this
keeps startup fast and avoids hammering TMDb's API for a library that rarely
changes. The cache is only bypassed when you explicitly click a row's **⟳**
refresh icon.

The cache lives alongside `settings.json`, at:

- `~/.config/PlexLibrary/tmdb_cache.json` — show/season/episode metadata
- `~/.config/PlexLibrary/tmdb_posters/` — poster images

Delete either to reset the cache; it will be rebuilt automatically as shows are
viewed or refreshed.

### Getting a free TMDb API key

1. Create a free account at [themoviedb.org/signup](https://www.themoviedb.org/signup).
2. Once logged in, go to **Settings → API** (or open
   [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) directly).
3. Click **Create** / **Request an API Key**, choose the **Developer** option, and
   fill in the short application form (you can describe it as a personal/hobby
   project — any reasonable description is accepted).
4. Once approved (usually instant), copy the **API Key (v3 auth)** value shown on
   that page.
5. In PlexLibrary, open **Settings** and paste it into the **TMDb API key** field,
   then click **Save**.

The key is stored in your OS keyring, the same way SMB/Plex credentials are —
it is never written to the plain-text settings file.

TMDb's free tier has no published hard daily cap for this kind of personal use and
requires no billing information.
