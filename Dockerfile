FROM python:3.11-slim-bookworm

ARG APP_VERSION=dev

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose Web UI port
EXPOSE 8000

# Create volume directories
RUN mkdir -p /config /data /config/cache
VOLUME ["/config", "/data"]

# Define environment variables with defaults
ENV NETPLEX_DB_PATH=/config/netplex.db \
    NETPLEX_CONFIG_DIR=/config \
    NETPLEX_CACHE_DIR=/config/cache \
    NETPLEX_DATA_DIR=/data \
    NETPLEX_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1

# Native Docker Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["python", "main.py"]
