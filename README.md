# NetPlex 🎬🍿

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vibecoded with Gemini 3.6 Flash](https://img.shields.io/badge/Vibecoded%20with-Gemini%203.6%20Flash-8E7CC3.svg)](https://deepmind.google/technologies/gemini/)

**NetPlex** is a Docker-based scraper and metadata synchronization utility that connects Netflix's weekly Top 10 rankings directly to your Plex Media Server.

It runs as a background Docker container, fetching the latest weekly Netflix Top 10 charts, downloading trailer videos (via `yt-dlp`) or generating zero-byte dummy stubs, and organizing them in a flat, Plex-optimized format. It also integrates with the Plex API to synchronize lists directly as custom Plex Collections or Playlists.

> **⚡ Built with AI**: Proudly vibecoded using **Gemini 3.6 Flash**.

> **⚖️ Formal Legal Notice & Disclaimer**:  
> **Non-Commercial Hobby Project**: NetPlex was created strictly as a non-commercial hobby and experimental personal project. There are no plans, intentions, or recommendations to commercialize, monetize, or offer this software as an enterprise/commercial service.  
> **Copyright & Content Rights**: Unauthorized downloading, copying, or distribution of copyrighted or private media content without explicit authorization from rights holders is illegal. NetPlex is designed strictly to operate on publicly accessible metadata and promotional trailer assets.  
> **Assumption of Risk & Liability**: Anyone using, deploying, or modifying this repository for any purpose does so **entirely at their own risk**. The authors, maintainers, and contributors explicitly disclaim all liability and legal responsibility for any misuse, policy violations, or damages resulting from the use of this software.

---

## 🚀 Key Features

* 📊 **Fetch Latest Weekly Top 10 Lists**: Scrapes weekly country-specific and global datasets from the Netflix Top 10 portal, focusing exclusively on the latest week's updates.
* 🖥️ **Tudum-Aesthetic Web UI**: Exposes an unauthenticated dashboard on port `8000`:
  * **Landing Page**: Replicates the visual identity of Netflix Tudum (using cached local CSS). Displays active country/global rankings in the exact order as Netflix. Works standalone without requiring Plex.
  * **Settings Page**: Manage monitored countries, configure Cron update schedules, toggle content formats, and link Plex via OAuth.
* 🎥 **Trailer Downloader Engine & Dummy File Mode**:
  * Uses `yt-dlp` to fetch promotional trailers and subtitle tracks (`.srt`).
  * **Optional Zero-Byte Dummy Trailers**: Supports creating fake 0-byte `.mp4`/`.mkv` files to mimic trailer downloads, allowing Plex to index items and build collections without consuming disk space or bandwidth.
* 📁 **Plex-Lean Library Directory**: Organizes media into standard, flat `movies/` and `tv/` subfolders mapped directly to a **dedicated Plex library**. TV show trailers are intelligently mapped as Season Specials (`SXXE00`) to maintain a clean layout.
* 🧹 **Auto-Cleanup & Tiny Database Footprint**: Only maintains the latest week's Top 10 dataset from Tudum, keeping SQLite database storage extremely small and automatically pruning old files.
* 🔌 **Plex API Integration**: Recommends setting up a **separate dedicated library** (e.g. *Netflix Top 10*) without merging into existing libraries. Fuzzy-matches titles in the Top 10 against your library to build custom Plex Collections/Playlists.
* ⏱️ **Cron-Based Scheduling**: Uses flexible Cron expressions (defaults to `0 0 * * 2` for weekly Tuesday runs when Netflix updates data) instead of rigid fixed intervals.
* 🛡️ **Offline-Resilient Workflow**: Media parsing and local file storage execute first. Plex synchronization follows as a secondary step; if Plex is disconnected or credentials expire, your local media folder remains intact.

---

## 🚀 Quick Start

NetPlex can be run directly using **Python** or containerized with **Docker Compose**.

### Option 1: Running via Docker Compose (Recommended)

1. Ensure `docker-compose.yml` is present in your project directory:
   ```yaml
   services:
     netplex:
       build: .
       container_name: netplex
       ports:
         - "8000:8000" # Web Settings UI & Dashboard
       volumes:
         - ./.docker/config:/config  # Stores SQLite database (netplex.db)
         - ./.docker/data:/data     # Plex-compatible media files (movies/ & tv/)
       restart: unless-stopped
   ```
2. Start the container:
   ```bash
   docker compose up -d
   ```
3. Open your browser and navigate to `http://localhost:8000`.

### Option 2: Running Locally via Python

1. Install system prerequisites (`ffmpeg` and `curl`):
   ```bash
   brew install ffmpeg curl  # macOS
   ```
2. Create and activate a virtual environment, then install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Set environment variables and run NetPlex:
   ```bash
   mkdir -p config media
   NETPLEX_DB_PATH=./config/netplex.db NETPLEX_CONFIG_DIR=./config NETPLEX_DATA_DIR=./media python main.py
   ```
4. Access the Web UI at `http://localhost:8000`.

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

---

## 🔒 Security & Reporting

Please review our [SECURITY.md](SECURITY.md) policy to report any security vulnerabilities responsibly.

---

## ⚖️ Legal Disclaimer & Limitation of Liability

1. **Hobby & Non-Commercial Purpose**: NetPlex is implemented purely as a personal hobby and experimental software project. It is not intended, recommended, or designed for commercial deployment, enterprise environments, or paid services. The maintainers have no plans to commercialize or monetize this project.
2. **Third-Party Trademarks**: NetPlex is an independent, community-driven project and is **not** affiliated, associated, authorized, endorsed by, or in any way officially connected with **Netflix, Inc.** or **Plex, Inc.**, or any of their subsidiaries or affiliates. All trademarks and brand names are the property of their respective owners.
3. **Copyright & Illegal Content Notice**: Users are strictly reminded that downloading, copying, storing, or distributing private, copyrighted, or non-public media content without the explicit consent of the copyright holder is illegal under applicable local and international copyright laws.
4. **Use at Own Risk**: Any person or organization using, executing, deploying, or distributing this codebase for any purpose does so **entirely at their own risk**. The creators and maintainers provide this software "as-is" without warranties of any kind and assume zero liability for any legal claims, service suspensions, data loss, or damages arising from its use.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for full details.


