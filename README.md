# NetPlex 🎬🍿

**NetPlex** is a Docker-based scraper and metadata synchronization utility that connects Netflix's weekly Top 10 rankings directly to your Plex Media Server.

It runs as a background Docker container, downloading the latest Netflix Top 10 charts, extracting trailer videos and subtitles directly from public Netflix CDNs, and organizing them in a flat, Plex-optimized format. It also integrates with the Plex API to synchronize lists directly as custom Plex Collections or Playlists.

---

## 🚀 Key Features

* 📊 **Latest Netflix Top 10 Data**: Scrapes weekly country-specific and global datasets from the Netflix Top 10 portal, focusing exclusively on the latest week's updates.
* 🖥️ **Tudum-Aesthetic 2-Page Web UI**: Exposes an unauthenticated dashboard on port `8000`:
  * **Landing Page**: Replicates the premium visual identity of Netflix Tudum (using cached local CSS). Displays the active country/global rankings in the exact order as Netflix. Works standalone without requiring Plex.
  * **Settings Page**: Manage monitored countries, toggle formats using checkboxes or radio buttons, and link Plex via OAuth.
* 🎥 **Direct Netflix Trailer Scraping**: Fetches public trailer videos (`.mp4` / `.mkv`) and subtitles (`.srt`) directly from Netflix's editorial CDNs (Tudum) rather than relying on YouTube crawlers.
* 📁 **Plex-Lean Library Directory**: Organizes media into standard, flat `movies/` and `tv/` subfolders mapped directly to Plex. TV show trailers are intelligently mapped as Season Specials (`SXXE00`) to maintain a clean layout.
* 🧹 **Auto-Cleanup Daemon**: Automatically deletes files and directories for items that drop out of the weekly Top 10 list, keeping your disk footprint lean.
* 🔌 **Plex API Integration**: Fuzzy-matches titles in the Top 10 against your existing libraries to build and re-order custom Plex Collections/Playlists.
* 🛡️ **Offline-Resilient Workflow**: Media parsing, downloading, and local file storage are executed first. Plex synchronization follows as a secondary step; if Plex is disconnected or credentials expire, your local media folder remains intact.

---

## 🐳 Quick Start (Docker Compose)

NetPlex is deployed exclusively using Docker. Create a `docker-compose.yml` file:

```yaml
services:
  netplex:
    image: netplex:latest
    container_name: netplex
    ports:
      - "8000:8000" # Web Settings UI
    volumes:
      - ./config:/config  # Stores SQLite database (netplex.db)
      - ./media:/data     # Plex-compatible media files (movies/ & tv/)
    restart: unless-stopped
```

1. Start the container:
   ```bash
   docker compose up -d
   ```
2. Open your web browser and navigate to `http://localhost:8000`.
3. Complete the Plex Link authentication and select the countries/formats you wish to track.

---

## 📂 Directory Layout

NetPlex maintains a highly optimized folder layout under the mapped `/data` volume. Same items are never duplicated, regardless of how many country charts they appear on:

```text
data/
├── movies/
│   ├── Inside Out 2 (2024)/
│   │   ├── Inside Out 2 (2024).mp4      # Trailer video
│   │   ├── Inside Out 2 (2024).en.srt   # Subtitles (if parsed)
│   │   └── movie.nfo                    # Plex NFO metadata
│   └── ...
└── tv/
    ├── Stranger Things (2016)/
    │   └── Season 01/
    │       ├── S01E00 - Trailer.mp4     # Trailer mapped as Episode 0 (Special)
    │       ├── S01E00 - Trailer.en.srt
    │       └── tvshow.nfo               # Series-level metadata NFO
    └── ...
```

---

## 📚 Documentation Reference

For more detailed technical descriptions, consult the guides below:

* 📐 **[architecture.md](docs/architecture.md)**: Explore the data pipeline, SQLite schemas, choices of technologies, and parsing workflow.
* ⚙️ **[configuration.md](docs/configuration.md)**: Details on Web UI settings, SQLite database configurations, and monitored tables.
* 🚢 **[deployment.md](docs/deployment.md)**: Complete guide on deploying NetPlex via Docker and Docker Compose.
* 🎛️ **[plex-integration.md](docs/plex-integration.md)**: Setup instructions for Plex libraries, NFO agents, and authentication details.
