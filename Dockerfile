FROM python:3.11-slim-bookworm

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
VOLUME ["/config", "/data"]

# Define environment variables with defaults
ENV NETPLEX_DB_PATH=/config/netplex.db \
    NETPLEX_CONFIG_DIR=/config \
    NETPLEX_CACHE_DIR=/config/cache \
    PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
