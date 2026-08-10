# NetPlex Architecture & System Design 📐

This document outlines the internal architecture, database schema, data pipelines, and technology choice for NetPlex.

---

## 🛠️ Technology Choice: Python

NetPlex is built using **Python**. The primary reasons for this architectural choice are:
1. **Plex Integration Ecosystem**: Python has the most mature, official, and robust Plex client library (`plexapi`). It supports advanced Plex interactions, including collection re-ordering and Plex PIN-based authentication.
2. **Built-in Database Support**: Python includes `sqlite3` in its standard library, allowing database-driven configuration and metadata caching without requiring separate database server installations or heavy drivers.
3. **Media Scraping Ecosystem**: Python excels at document parsing. Using libraries like `requests` and `BeautifulSoup`, it can parse public Netflix title structures and editorial CDNs to isolate raw trailer files and subtitle tracks.
4. **Lightweight Web Stack**: Python supports clean, micro-web frameworks like FastAPI or Flask, enabling a clean Web Settings UI with low memory overhead.

---

## 🏗️ System Components

NetPlex is designed with two mapped volumes:
* `/config`: Hosts application database files, certificates, and runtime cache.
* `/data`: Structured media directory containing Plex-optimized folders (`movies/` and `tv/`).

```mermaid
graph TD
    %% Component Layers %%
    subgraph config_volume ["Config Volume (/config)"]
        DB[("netplex.db (SQLite)")]
    end
    
    subgraph web_interface ["Web Interface (Port 8000)"]
        UI["Landing & Settings Pages"] -->|Read/Write| DB
    end
    
    subgraph ingestion_pipeline ["Ingestion Pipeline"]
        C["Crawler Cron"] -->|1. Query Monitored Config| DB
        C -->|2. Fetch Latest Weekly List| N["Netflix Top 10 API"]
        C -->|3. Resolve Tudum/CDN Media| CD["Netflix CDN / Web Scraper"]
        CD -->|Download Video & Subtitles| DV[("/data Volume")]
    end
    
    subgraph sync_pipeline ["Sync Pipeline"]
        C -->|4. Trigger Plex Sync| PX["Plex Sync Agent"]
        PX -->|5. Read Cache| DB
        PX -->|6. Connect & Update Collections| PM["Plex Media Server"]
    end
    
    style config_volume fill:#1b1b1e,stroke:#3a3a3c
    style web_interface fill:#1b1b1e,stroke:#3a3a3c
```

---

## 🖥️ Web Server & UI Design

NetPlex exposes a lightweight web server that renders a frontend on port `8000`. 

### 1. Access Control
Access to the NetPlex dashboard is **completely unauthenticated by default**. This allows you to view your local Top 10 collection immediately without credentials. User credentials are strictly used for Plex API synchronization in the background.

### 2. Page Structure
The frontend consists of two main pages:
* **Landing Page (`/`)**: A clean grid view showing the active Top 10 lists fetched from the SQLite database. Shows rankings in the exact Netflix order (1 through 10), complete with local summary data and video trailer overlays. This page operates standalone even if a Plex server is not connected.
* **Settings Page (`/settings`)**: Configures the scraper. Includes:
  * Checkboxes or radio buttons to customize tracked countries and content formats (e.g. checkbox for `Movies` and `TV Shows`).
  * Plex sign-in redirect button (Plex OAuth).
  * Synchronization log viewer and manual crawl triggers.

### 3. Tudum Visual Identity & Local CSS Styling
* **Aesthetics**: The UI closely matches the Netflix Tudum editorial look, featuring a bold dark background, Netflix red accents (`#E50914`), heavy header typography, and smooth card zoom hovers.
* **Asset Caching**: To maintain style fidelity, NetPlex's crawler parses the stylesheets (`.css` files) used on the Netflix Tudum website, extracts core styles (like color variables and cards styling), and saves them locally under `/config/www/tudum.css`. The web server serves these locally-cached CSS files, ensuring the UI stays stylized even in offline deployments.

---

## 🗄️ Database Schema (`netplex.db`)

All application settings, monitored states, and download logs are stored in a SQLite database located at `/config/netplex.db`.

```mermaid
erDiagram
    settings {
        varchar key PK
        varchar value
    }
    monitored_countries {
        varchar country_code PK
        varchar formats
    }
    media_items {
        integer id PK
        varchar title
        varchar type
        integer release_year
        varchar season_name
        varchar folder_name
        varchar file_path
        varchar status
        timestamp added_at
        timestamp last_seen_at
    }
    rankings {
        integer id PK
        varchar country_code
        varchar category
        integer rank
        varchar week
        integer media_item_id FK
    }
    media_items ||--o{ rankings : "appears in"
```

### 1. `settings` Table
Stores general global settings editable via the Web UI:
* `plex_url`: The address of the Plex Media Server.
* `plex_token`: The authenticated Plex API token.
* `update_interval_hours`: Frequency of scraper executions.
* `log_level`: Level of detail in the execution logs.

### 2. `monitored_countries` Table
Stores countries currently monitored by the scraper:
* `country_code` (e.g. `TR`, `US`).
* `formats`: `movies`, `tv`, or `both`.

### 3. `media_items` Table
Tracks unique movies and series downloaded on disk, ensuring files are not duplicated even if they appear in multiple country rankings:
* `id` (Primary Key).
* `title`: Title of the movie or show.
* `type`: `movie` or `tv`.
* `release_year`: Extracted release year.
* `season_name`: Extracted season name (e.g., `Season 1`, empty for movies).
* `folder_name`: Name of the directory on disk (e.g., `Stranger Things (2016)`).
* `status`: `pending`, `downloaded`, or `failed`.
* `last_seen_at`: Timestamp of the last time this item appeared in any active Top 10 list.

### 4. `rankings` Table
Tracks weekly rankings:
* `id` (Primary Key).
* `country_code` (e.g. `US`, `TR`).
* `category` (e.g. `Films`, `TV`).
* `rank` (1 to 10).
* `week` (e.g., `2026-08-09`).
* `media_item_id` (Foreign Key referencing `media_items.id`).

---

## 🔄 Execution Sequence & Resiliency

NetPlex prioritizes keeping local media updated before interacting with Plex. If Plex is unavailable or offline, the local database and files remain fully functional.

```mermaid
sequenceDiagram
    autonumber
    participant CR as Crawler
    participant DB as SQLite DB
    participant NF as Netflix Tudum
    participant FS as Local Filesystem
    participant PL as Plex API
    
    CR->>DB: Load settings (Monitored countries, formats)
    DB-->>CR: Config Data
    CR->>NF: Fetch latest weekly Top 10 lists
    NF-->>CR: Weekly Top 10 Data
    CR->>DB: Update rankings & identify new items
    
    loop For each new Top 10 item
        CR->>NF: Parse Tudum article/details for video & subtitles
        NF-->>CR: Direct CDN video/subtitle URLs (.mp4 & .vtt)
        CR->>FS: Write files (movies/ or tv/)
        CR->>DB: Mark item as 'downloaded'
    end
    
    CR->>DB: Identify orphaned items (not in latest rankings)
    CR->>FS: Remove orphaned files from disk
    CR->>DB: Remove orphaned records from active list
    
    critical Try Plex Sync
        CR->>PL: Connect with Plex Token
        PL-->>CR: Session OK
        CR->>PL: Find matching library titles
        CR->>PL: Rebuild and order Collections (1 to 10)
    option Plex Offline / Token Expired
        CR->>CR: Log connection error and skip Plex Sync
        Note over CR: Local files and DB remain updated
    end
```

---

## 🔗 Related Documentation

* Returning to home: **[README.md](../README.md)**
* Configuration reference: **[configuration.md](configuration.md)**
* Deployment instructions: **[deployment.md](deployment.md)**
* Plex configuration and scanning: **[plex-integration.md](plex-integration.md)**
