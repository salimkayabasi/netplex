# NetPlex Execution & Deployment Guide 🚀🚢

NetPlex can be executed directly on your host machine using **Python** (ideal for development, testing, or custom setups) or deployed as a **Docker container** (recommended for production).

---

## 🐍 1. Running Locally via Python

### System Requirements
* **Python 3.11** or higher
* **ffmpeg**: Required for processing video trailer streams and muxing media assets.
  * **macOS**: `brew install ffmpeg`
  * **Ubuntu/Debian**: `sudo apt update && sudo apt install -y ffmpeg curl`
  * **Windows**: `choco install ffmpeg` or download from official builds.
* **curl**: Used for network checks and fetching stylesheets.

### Setup Instructions

1. **Clone the Repository & Navigate to Workspace**:
   ```bash
   git clone https://github.com/salimkayabasi/netplex.git
   cd netplex
   ```

2. **Create and Activate Virtual Environment**:
   * macOS / Linux:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   * Windows (PowerShell):
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```

3. **Install Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Prepare Local Directories**:
   Create folders for configuration persistence and media storage:
   ```bash
   mkdir -p config media
   ```

5. **Set Environment Variables & Launch NetPlex**:
   Run NetPlex with custom environment variable paths pointing to your local directories:

   * **Linux / macOS**:
     ```bash
     NETPLEX_DB_PATH=./config/netplex.db \
     NETPLEX_CONFIG_DIR=./config \
     NETPLEX_DATA_DIR=./media \
     NETPLEX_HOST=127.0.0.1 \
     NETPLEX_PORT=8000 \
     python main.py
     ```

   * **Windows (PowerShell)**:
     ```powershell
     $env:NETPLEX_DB_PATH="./config/netplex.db"
     $env:NETPLEX_CONFIG_DIR="./config"
     $env:NETPLEX_DATA_DIR="./media"
     $env:NETPLEX_HOST="127.0.0.1"
     $env:NETPLEX_PORT="8000"
     python main.py
     ```

6. **Verify and Access Web UI**:
   Open your browser at `http://localhost:8000` to access the Tudum landing page and settings interface.

7. **Running Automated Unit Tests**:
   ```bash
   PYTHONPATH=. pytest
   ```

---

## 🐳 2. Running via Docker & Docker Compose

### Volume Mappings
When containerized, NetPlex expects two main volume mounts:
1. **`/config`**: Persists settings and caching state. Stores the SQLite database (`netplex.db`).
2. **`/data`**: Target media directory where `/data/movies` and `/data/tv` are generated for Plex scanning.

---

### Option A: Docker Compose (Recommended)

1. Create a `docker-compose.yml` file in your application directory:

```yaml
services:
  netplex:
    build: .
    container_name: netplex
    ports:
      - "8000:8000"          # Web Settings UI and Tudum Dashboard
    volumes:
      - ./.docker/config:/config     # SQLite database and web assets
      - ./.docker/data:/data        # Media output folder (mapped to Plex share)
    environment:
      - NETPLEX_DB_PATH=/config/netplex.db
      - NETPLEX_CONFIG_DIR=/config
      - NETPLEX_DATA_DIR=/data
      - NETPLEX_HOST=0.0.0.0
      - NETPLEX_PORT=8000
    restart: unless-stopped
```

2. Launch the application:
   ```bash
   docker compose up -d
   ```

3. View live execution logs:
   ```bash
   docker compose logs -f
   ```

---

### Option B: Docker CLI (Manual Execution)

1. **Build Docker Image**:
   ```bash
   docker build -t netplex:latest .
   ```

2. **Run Container**:
   ```bash
   docker run -d \
     --name netplex \
     -p 8000:8000 \
     -v $(pwd)/.docker/config:/config \
     -v $(pwd)/.docker/data:/data \
     -e NETPLEX_DB_PATH=/config/netplex.db \
     -e NETPLEX_CONFIG_DIR=/config \
     -e NETPLEX_DATA_DIR=/data \
     netplex:latest
   ```

3. **Check Container Logs**:
   ```bash
   docker logs -f netplex
   ```

---

## ⚙️ Environment Variables Summary

| Variable | Description | Default (Docker) | Default (Local Python) |
| :--- | :--- | :--- | :--- |
| `NETPLEX_DB_PATH` | Path to SQLite database file | `/config/netplex.db` | `./config/netplex.db` |
| `NETPLEX_CONFIG_DIR` | Path to configuration & cache folder | `/config` | `./config` |
| `NETPLEX_DATA_DIR` | Path to downloaded media files (`movies/` & `tv/`) | `/data` | `./media` or `./data` |
| `NETPLEX_HOST` | Web server bind IP address | `0.0.0.0` | `0.0.0.0` or `127.0.0.1` |
| `NETPLEX_PORT` | Web server listening port | `8000` | `8000` |
| `NETPLEX_CRON_SCHEDULE` | Cron expression for weekly updates | `0 0 * * 2` | `0 0 * * 2` |
| `PYTHONUNBUFFERED` | Disable Python print log buffering | `1` | `1` |

---

## 🔗 Related Documentation

* Returning to home: **[README.md](../README.md)**
* Ingestion pipeline and database schemas: **[architecture.md](architecture.md)**
* Configuration reference: **[configuration.md](configuration.md)**
* Plex configuration and scanning: **[plex-integration.md](plex-integration.md)**
