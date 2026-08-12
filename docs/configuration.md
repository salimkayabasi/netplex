# NetPlex Configuration Reference ⚙️

NetPlex avoids complex environment variables or messy configuration files. All user settings are managed directly through a Web UI dashboard and stored inside a local SQLite database at `/config/netplex.db`.

---

## ⚙️ Environment Variables

The container / application behavior can be customized using the following environment variables:

| Environment Variable | Description | Default Value |
| :--- | :--- | :--- |
| `NETPLEX_DB_PATH` | Path to SQLite database file | `/config/netplex.db` |
| `NETPLEX_CONFIG_DIR` | Directory for logs and static assets | `/config` |
| `NETPLEX_CACHE_DIR` | Directory for temporary TSV downloads | `/config/cache` |
| `NETPLEX_DATA_DIR` | Target media directory for Plex libraries | `/data` |
| `NETPLEX_HOST` | Web application server bind IP | `0.0.0.0` |
| `NETPLEX_PORT` | Web application server port | `8000` |
| `NETPLEX_LOG_LEVEL` | Application logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `NETPLEX_LOG_FILTER` | Filter console logs to specific logger name (e.g. `netplex.crawler`) | None |

---

## 🖥️ Web UI Settings Menu

When the Docker container is running, access the dashboard at `http://localhost:8000`. 

> [!NOTE]
> By default, NetPlex requires **no authentication** to access the dashboard. Anyone on your local network can view the Top 10 landing page and edit configurations. Plex credentials are only required for synchronizing local files with Plex collections.

### 1. Plex Authentication Settings
* **Plex URL**: The local IP address and port of your Plex Media Server (e.g. `http://192.168.1.50:32400`).
* **Plex Authentication Status**: Shows whether the container is currently authenticated with Plex.
* **Sign In with Plex (OAuth Flow)**: A button that opens a secure Plex sign-in popup (identical to Overseerr). You log in on Plex's official domain and authorize the application, which automatically saves the token without copy-pasting any codes.
* **Manual Plex Token**: An input field to manually paste a Plex Token if you prefer not to use the OAuth sign-in popup.

### 2. Country & Format Monitored Lists
Rather than scanning all 90+ countries tracked by Netflix, NetPlex only parses the countries you select.
* **Monitored Countries**: A multi-select checklist of active countries to scrape (e.g., Turkey, United States, Germany).
* **Content Types per Country**: Grouped **Checkboxes** or **Radio Buttons** for each monitored country to customize tracked lists:
  * `[ ] Movies` (Films lists)
  * `[ ] TV Shows` (TV lists)
  * Selecting both functions identically to a `Both` sync.

### 3. Sync & Download Options
* **Cron Schedule**: Standard 5-field cron expression for scheduling scraper runs (defaults to `0 0 * * 2` / weekly on Tuesdays at midnight, since Netflix publishes new Top 10 data weekly on Tuesdays).
* **Trailer Downloader Engine**: Uses `yt-dlp` to fetch trailer videos and subtitle tracks.
* **Dummy (Zero-Byte) Media Mode**: Toggle to generate fake 0-byte `.mp4`/`.mkv` files instead of downloading full video streams, allowing Plex to index items and build collections without using disk storage or bandwidth.
* **Trailer Subtitles**: Toggle to enable/disable downloading SRT subtitles for trailers.
* **Preferred Subtitle Languages**: List of languages (e.g. `en`) to try fetching.

---

## 🗄️ Database Storage Details

Settings are saved in the `settings` and `monitored_countries` tables of `/config/netplex.db`. If you need to debug or edit them directly inside the container or mounted volume:

### 1. `settings` Table
Contains key-value strings:

```sql
SELECT * FROM settings;
```

| key | value |
| :--- | :--- |
| `plex_url` | `http://192.168.1.50:32400` |
| `plex_token` | `xYz123456789abcDEF` |
| `cron_expression` | `0 0 * * 2` |
| `log_level` | `INFO` |
| `dummy_media_mode` | `false` |

### 2. `monitored_countries` Table
Tracks country-specific formats:

```sql
SELECT * FROM monitored_countries;
```

| country_code | formats |
| :--- | :--- |
| `TR` | `both` |
| `US` | `movies` |
| `DE` | `tv` |

---

## 🔗 Related Documentation

* Returning to home: **[README.md](../README.md)**
* Ingestion pipeline and system components: **[architecture.md](architecture.md)**
* Deployment instructions: **[deployment.md](deployment.md)**
* Plex configuration and scanning: **[plex-integration.md](plex-integration.md)**
