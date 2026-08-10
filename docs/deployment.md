# NetPlex Deployment Guide 🚢

NetPlex is officially deployed and distributed as a Docker container. This ensures all dependencies (including Python, web servers, and database tools) run in a standardized sandbox.

---

## 🐳 Volume Mappings

NetPlex requires two volume mount points mapped to your host system:
1. **`/config`**: Persists settings and caching state. Stores the `netplex.db` SQLite database.
2. **`/data`**: Stores the structured media library. Under this path, NetPlex will generate two subfolders: `/data/movies` and `/data/tv`. Map this directory to your Plex media share.

---

## 🏗️ Docker Compose Deployment

Docker Compose is the recommended way to deploy NetPlex.

Create a `docker-compose.yml` file:
```yaml
services:
  netplex:
    image: netplex:latest
    container_name: netplex
    ports:
      - "8000:8000"          # Port for the Web Settings UI
    volumes:
      - /opt/netplex/config:/config  # Database and settings volume
      - /mnt/media/netflix-top10:/data # Plex-accessible media volume
    restart: unless-stopped
```

### 1. Launch the Container
Run the following command in the directory containing `docker-compose.yml`:
```bash
docker compose up -d
```

### 2. View Application Logs
To inspect crawler progress or debug issues:
```bash
docker logs -f netplex
```

---

## 🛠️ The Dockerfile

If you are compiling or building NetPlex locally from source, use the following `Dockerfile`:

```dockerfile
FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Set up directory structure
WORKDIR /app

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose Web UI Port
EXPOSE 8000

# Define volumes
VOLUME ["/config", "/data"]

# Run server
ENTRYPOINT ["python", "main.py"]
```

---

## 🔗 Related Documentation

* Returning to home: **[README.md](../README.md)**
* Ingestion pipeline and database schemas: **[architecture.md](architecture.md)**
* Configuration reference: **[configuration.md](configuration.md)**
* Plex configuration and scanning: **[plex-integration.md](plex-integration.md)**
