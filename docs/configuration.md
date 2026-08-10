# NetPlex Configuration Reference ⚙️

NetPlex avoids complex environment variables or messy configuration files. All user settings are managed directly through a Web UI dashboard and stored inside a local SQLite database at `/config/netplex.db`.

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
* **Update Interval**: The interval in hours between checks (defaults to `168` hours / 7 days since Netflix updates data weekly on Tuesdays).
* **Trailer Subtitles**: Toggle to enable/disable downloading SRT subtitles for trailers.
* **Preferred Subtitle Languages**: List of languages (e.g., `tr, en`) to try fetching.

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
| `update_interval_hours` | `168` |
| `log_level` | `INFO` |

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
