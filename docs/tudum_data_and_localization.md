# Netflix Tudum Data Availability & Content Localization Guide

This document details all metadata fields accessible directly from the Netflix Tudum portal per content type (Movies & TV Shows) and outlines the strategy for retrieving localized content titles in their native regional languages.

---

## 1. Data Available from Netflix Tudum per Content Type

Netflix Tudum exposes data through two primary mechanisms:
1. **Top 10 TSV Datasets** (`all-weeks-global.tsv` & `all-weeks-countries.tsv`)
2. **Page GraphQL Models & Media Assets** (`PulseTop10ItemEntity` on `netflix.com/tudum/top10/<country>`)

### A. Movies (Films)

| Field Name | Source | Description & Format | Example |
| :--- | :--- | :--- | :--- |
| `videoId` | GraphQL (`PulseTop10ItemEntity`) | Netflix unique numeric content identifier | `82742346` |
| `title` | TSV & GraphQL | Global English title string | `"Are We Happy?"` |
| `show_title` | TSV | English show/film title | `"Gladiator II"` |
| `releaseYear` | GraphQL | 4-digit release year integer | `2026` |
| `weekly_rank` | TSV | Ranking position (1 to 10) | `1` |
| `weekly_views` | TSV | Total views recorded during the week | `14200000` |
| `weekly_hours_viewed` | TSV | Total hours viewed during the week | `28400000` |
| `cumulative_weeks_in_top_10` | TSV | Cumulative number of weeks in Top 10 | `3` |
| `shortSynopsis` | GraphQL | Short English plot summary | `"After their divorce..."` |
| `maturityRating` | GraphQL | Content age classification | `"10+"`, `"16+"` |
| `runtimeSeconds` | GraphQL | Total movie duration in seconds | `7200` |
| `poster_url` | GraphQL (`storyArt` / `sdpArt`) | High-resolution poster/backdrop image URL | `https://dnm.nflximg.net/...` |
| `logo_url` | GraphQL (`logoArt`) | Transparent PNG title logo image URL | `https://dnm.nflximg.net/...` |
| `video_url` | Tudum Page HTML | Direct trailer video stream (`.mp4` / `.mkv`) | `https://.../video.mp4` |
| `subtitle_url` | Tudum Page HTML | Trailer subtitle file (`.vtt`) | `https://.../sub.vtt` |

---

### B. TV Shows (Series & Seasons)

| Field Name | Source | Description & Format | Example |
| :--- | :--- | :--- | :--- |
| `videoId` | GraphQL (`PulseTop10ItemEntity`) | Netflix unique numeric content identifier | `81902148` |
| `show_title` | TSV | Main TV Show title in English | `"Stranger Things"` |
| `season_title` | TSV | Season name string | `"Stranger Things 4"` |
| `season_name` | Derived | Cleaned season identifier | `"Season 4"` / `"04"` |
| `releaseYear` | GraphQL | 4-digit release year integer | `2024` |
| `weekly_rank` | TSV | Ranking position (1 to 10) | `2` |
| `weekly_views` | TSV | Total views recorded during the week | `9800000` |
| `weekly_hours_viewed` | TSV | Total hours viewed during the week | `45000000` |
| `cumulative_weeks_in_top_10` | TSV | Cumulative weeks in Top 10 | `6` |
| `shortSynopsis` | GraphQL | Short English plot summary | `"When a young boy vanishes..."` |
| `maturityRating` | GraphQL | Content age classification | `"18+"` |
| `poster_url` | GraphQL (`storyArt` / `sdpArt`) | High-resolution poster/backdrop image URL | `https://dnm.nflximg.net/...` |
| `logo_url` | GraphQL (`logoArt`) | Transparent PNG title logo image URL | `https://dnm.nflximg.net/...` |
| `video_url` | Tudum Page HTML | Direct trailer video stream (`.mp4` / `.mkv`) | `https://.../video.mp4` |
| `subtitle_url` | Tudum Page HTML | Trailer subtitle file (`.vtt`) | `https://.../sub.vtt` |

---

## 2. Localization & Native Content Names

### Is Localized Data (Native Language Titles) Available Directly from Netflix Tudum?
**No.** Netflix Tudum Top 10 global pages and TSV data files publish titles **exclusively in English**, even on country-specific pages.

### Strategy to Fetch Native Regional Titles
To display authentic localized titles in the native language of the target region alongside the global English names, the following secondary sources/fallback options are used:

1. **Netflix Title Page Scraper with Locale Headers**:
   - Querying `https://www.netflix.com/<country_code>/title/<netflix_id>` with HTTP headers matching the target locale (e.g., `Accept-Language: <country_code>`).
   - Extracts localized title tags (`<meta property="og:title">` or `<h1>`).

2. **TMDB (The Movie Database) Search API**:
   - Querying `/search/movie` or `/search/tv` with the target country locale code.
   - Provides localized title (`title` / `name`), localized poster artwork, and localized overview.

---

## 3. Storage in NetPlex Database

NetPlex stores localized titles in the `media_items` table:

```sql
CREATE TABLE media_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,          -- Primary English Title (from Tudum)
    local_title TEXT,             -- Localized Title (in region's native language)
    type TEXT NOT NULL,           -- 'movie' or 'tv'
    release_year INTEGER NOT NULL,
    season_name TEXT,
    folder_name TEXT NOT NULL,
    file_path TEXT,
    poster_url TEXT,
    status TEXT NOT NULL
);
```

When `local_title` is present and differs from `title`, NetPlex renders both titles in the format:
`Original Title / Local Title`.

