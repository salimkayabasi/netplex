import os
import re
import urllib.request
import logging
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.database import (
    _get_connection,
    get_monitored_countries,
    get_active_rankings,
    get_setting
)

logger = logging.getLogger(__name__)

# Base directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="NetPlex Web Server")

# Mount /static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

from src.web.routes_settings import router as settings_router
app.include_router(settings_router)

# Default DB Path configuration
DEFAULT_DB_PATH = os.environ.get("NETPLEX_DB_PATH", "/config/netplex.db")
DEFAULT_CONFIG_DIR = os.environ.get("NETPLEX_CONFIG_DIR", "/config")

def get_db_path(request: Request) -> str:
    return getattr(request.app.state, "db_path", DEFAULT_DB_PATH)

COUNTRY_NAMES = {
    "GLOBAL": "Global",
    "US": "United States",
    "GB": "United Kingdom",
    "CA": "Canada",
    "AU": "Australia",
    "DE": "Germany",
    "FR": "France",
    "ES": "Spain",
    "IT": "Italy",
    "JP": "Japan",
    "KR": "South Korea",
    "BR": "Brazil",
    "MX": "Mexico",
    "IN": "India",
    "TR": "Turkey"
}

@app.get("/", response_class=HTMLResponse)
def landing_page(
    request: Request,
    category: str = Query("Movies")
):
    db_path = get_db_path(request)
    
    # Get monitored countries in settings menu insertion order
    monitored = []
    try:
        monitored = get_monitored_countries(db_path)
    except Exception:
        pass

    # Get latest week from rankings table
    latest_week = ""
    try:
        conn = _get_connection(db_path)
        cursor = conn.execute("SELECT week FROM rankings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            latest_week = row["week"]
        conn.close()
    except Exception:
        pass

    # Build country sections in the exact order set from the settings menu
    country_sections = []
    for m in monitored:
        code = m["country_code"]
        name = COUNTRY_NAMES.get(code, code)
        rankings_for_country = []
        if latest_week:
            try:
                rankings_for_country = get_active_rankings(db_path, code, category, latest_week)
            except Exception:
                pass
        country_sections.append({
            "country_code": code,
            "country_name": name,
            "formats": m.get("formats", "movie,tv"),
            "rankings": rankings_for_country
        })

    primary_rankings = country_sections[0]["rankings"] if country_sections else []

    dummy_media_mode = False
    try:
        dummy_media_mode = get_setting(db_path, "dummy_media_mode", "false").lower() in ("true", "1", "yes", "on")
    except Exception:
        pass

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "monitored_countries": monitored,
            "selected_category": category,
            "current_week": latest_week,
            "rankings": primary_rankings,
            "country_sections": country_sections,
            "dummy_media_mode": dummy_media_mode
        }
    )

@app.get("/stream/video/{item_id}")
def stream_video(
    request: Request,
    item_id: int,
    range: Optional[str] = Header(None)
):
    db_path = get_db_path(request)

    dummy_media_mode = False
    try:
        dummy_media_mode = get_setting(db_path, "dummy_media_mode", "false").lower() in ("true", "1", "yes", "on")
    except Exception:
        pass
    
    # Query file_path for media_item
    file_path = None
    try:
        conn = _get_connection(db_path)
        cursor = conn.execute("SELECT file_path FROM media_items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if row:
            file_path = row["file_path"]
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Media file not found")

    # Security: Validate path traversal to ensure file is inside allowed NETPLEX_DATA_DIR
    data_dir = os.environ.get("NETPLEX_DATA_DIR", "/data")
    abs_media_dir = os.path.realpath(data_dir)
    abs_file_path = os.path.realpath(file_path)
    if os.path.commonpath([abs_file_path, abs_media_dir]) != abs_media_dir or abs_file_path == abs_media_dir:
        logger.error(f"Security: Path traversal blocked for file '{file_path}' outside '{abs_media_dir}'")
        raise HTTPException(status_code=403, detail="Access denied: Invalid media path")

    file_size = os.path.getsize(file_path)

    if dummy_media_mode or file_size == 0:
        raise HTTPException(status_code=400, detail="Dummy media mode enabled: video streaming unavailable for zero-byte media stubs")

    if range:
        # Parse range header: e.g. "bytes=0-1023"
        range_match = re.search(r"bytes=(\d+)-(\d*)", range)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            if start >= file_size or end >= file_size:
                raise HTTPException(status_code=416, detail="Requested range not satisfiable")

            chunk_size = (end - start) + 1

            def stream_bytes():
                with open(file_path, "rb") as video:
                    video.seek(start)
                    bytes_remaining = chunk_size
                    while bytes_remaining > 0:
                        read_size = min(8192, bytes_remaining)
                        data = video.read(read_size)
                        if not data:
                            break
                        bytes_remaining -= len(data)
                        yield data

            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Content-Type": "video/mp4",
            }
            return StreamingResponse(stream_bytes(), status_code=206, headers=headers)

    return FileResponse(file_path, media_type="video/mp4")
