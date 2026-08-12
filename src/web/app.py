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

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_config_www_mounted(DEFAULT_CONFIG_DIR)
    yield

app = FastAPI(title="NetPlex Web Server", lifespan=lifespan)

# Mount /static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Dynamic mount helper for /config/www
def ensure_config_www_mounted(config_dir: str = "/config"):
    www_dir = os.path.join(config_dir, "www")
    os.makedirs(www_dir, exist_ok=True)
    # Check if already mounted
    for route in app.routes:
        if getattr(route, "path", None) == "/config/www":
            return www_dir
    app.mount("/config/www", StaticFiles(directory=www_dir), name="config_www")
    return www_dir

templates = Jinja2Templates(directory=TEMPLATES_DIR)

from src.web.routes_settings import router as settings_router
app.include_router(settings_router)

# Default DB Path configuration
DEFAULT_DB_PATH = os.environ.get("NETPLEX_DB_PATH", "/config/netplex.db")
DEFAULT_CONFIG_DIR = os.environ.get("NETPLEX_CONFIG_DIR", "/config")

def get_db_path(request: Request) -> str:
    return getattr(request.app.state, "db_path", DEFAULT_DB_PATH)

def download_and_cache_tudum_css(config_dir: str = "/config", html_content: Optional[str] = None, css_content: Optional[str] = None) -> str:
    """
    Crawls Tudum landing page or parses html_content to locate, download, and cache the stylesheet CSS locally under {config_dir}/www/tudum.css.
    """
    www_dir = os.path.join(config_dir, "www")
    os.makedirs(www_dir, exist_ok=True)
    target_css_path = os.path.join(www_dir, "tudum.css")

    if css_content:
        with open(target_css_path, "w", encoding="utf-8") as f:
            f.write(css_content)
        return target_css_path

    if not html_content:
        try:
            tudum_url = "https://www.netflix.com/tudum/"
            req = urllib.request.Request(tudum_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html_content = resp.read().decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to fetch live Tudum HTML: {e}")

    stylesheet_url = None
    if html_content:
        # Match <link ... rel="stylesheet" ... href="..."> or rel='stylesheet'
        matches = re.findall(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\'][^>]*>', html_content, re.IGNORECASE)
        if not matches:
            matches = re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        if matches:
            stylesheet_url = matches[0]

    downloaded_css = ""
    if stylesheet_url:
        if not stylesheet_url.startswith("http"):
            stylesheet_url = f"https://www.netflix.com{stylesheet_url}"
        try:
            req = urllib.request.Request(stylesheet_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                downloaded_css = resp.read().decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to download Tudum CSS from {stylesheet_url}: {e}")

    if not downloaded_css:
        # Fallback CSS template
        downloaded_css = """/* Cached Tudum Fallback Branding */
:root {
    --tudum-primary-bg: #141414;
    --tudum-brand-red: #E50914;
}"""

    with open(target_css_path, "w", encoding="utf-8") as f:
        f.write(downloaded_css)

    return target_css_path

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
