import os
import re
import urllib.request
import logging
import xml.etree.ElementTree as ET
from typing import Optional
from fastapi import FastAPI, Request, HTTPException, Header, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.database import (
    _get_connection,
    get_monitored_countries,
    get_active_rankings,
    get_setting,
    get_media_item_by_netflix_id,
    get_prev_next_media_items
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

def find_and_parse_nfo(media_item: dict) -> dict:
    data_dir = os.environ.get("NETPLEX_DATA_DIR", "/data")
    possible_dirs = []
    
    file_path = media_item.get("file_path")
    if file_path:
        d = os.path.dirname(file_path)
        possible_dirs.append(d)
        possible_dirs.append(os.path.dirname(d))
        
    folder_name = media_item.get("folder_name")
    if folder_name:
        possible_dirs.append(os.path.join(data_dir, "movies", folder_name))
        possible_dirs.append(os.path.join(data_dir, "tv", folder_name))
        
    nfo_path = None
    for d in possible_dirs:
        if not d or not os.path.exists(d):
            continue
        for candidate in ["movie.nfo", "tvshow.nfo"]:
            cp = os.path.join(d, candidate)
            if os.path.exists(cp):
                nfo_path = cp
                break
        if nfo_path:
            break
        try:
            for fname in os.listdir(d):
                if fname.lower().endswith(".nfo"):
                    nfo_path = os.path.join(d, fname)
                    break
        except Exception:
            pass
        if nfo_path:
            break

    nfo_data = {
        "plot": None,
        "tagline": None,
        "maturity_rating": None,
        "runtime_seconds": None,
        "studio": None,
        "country": None,
        "genres": [],
        "directors": [],
        "creators": [],
        "actors": [],
    }
    
    if nfo_path and os.path.exists(nfo_path):
        try:
            tree = ET.parse(nfo_path)
            root = tree.getroot()
            
            plot_el = root.find("plot")
            if plot_el is not None and plot_el.text:
                nfo_data["plot"] = plot_el.text.strip()

            tagline_el = root.find("tagline")
            if tagline_el is not None and tagline_el.text:
                nfo_data["tagline"] = tagline_el.text.strip()

            mpaa_el = root.find("mpaa")
            if mpaa_el is None:
                mpaa_el = root.find("certification")
            if mpaa_el is not None and mpaa_el.text:
                nfo_data["maturity_rating"] = mpaa_el.text.strip()
            
            runtime_el = root.find("runtime")
            if runtime_el is not None and runtime_el.text and runtime_el.text.strip().isdigit():
                nfo_data["runtime_seconds"] = int(runtime_el.text.strip()) * 60

            studio_el = root.find("studio")
            if studio_el is not None and studio_el.text:
                nfo_data["studio"] = studio_el.text.strip()

            country_el = root.find("country")
            if country_el is not None and country_el.text:
                nfo_data["country"] = country_el.text.strip()

            nfo_data["genres"] = [g.text.strip() for g in root.findall("genre") if g.text and g.text.strip()]
            nfo_data["directors"] = [d.text.strip() for d in root.findall("director") if d.text and d.text.strip()]
            nfo_data["creators"] = [c.text.strip() for c in root.findall("credits") if c.text and c.text.strip()]
            
            actors = []
            for actor_el in root.findall("actor"):
                name_el = actor_el.find("name")
                if name_el is not None and name_el.text and name_el.text.strip():
                    actors.append(name_el.text.strip())
            nfo_data["actors"] = actors
        except Exception as e:
            logger.error(f"Error reading NFO at {nfo_path}: {e}")
            
    return nfo_data

def render_landing_page(request: Request, category: str):
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

@app.get("/", response_class=HTMLResponse)
def landing_page_root(request: Request, category: Optional[str] = Query(None)):
    if category:
        if category.lower() == "tv":
            return RedirectResponse(url="/tv", status_code=307)
        return RedirectResponse(url="/movies", status_code=307)
    return RedirectResponse(url="/movies", status_code=307)

@app.get("/movies", response_class=HTMLResponse)
def movies_page(request: Request):
    return render_landing_page(request, "Movies")

@app.get("/tv", response_class=HTMLResponse)
def tv_page(request: Request):
    return render_landing_page(request, "TV")

def render_detail_page(request: Request, netflix_id: str, item_type: str, country: Optional[str] = None):
    db_path = get_db_path(request)
    media_item = get_media_item_by_netflix_id(db_path, netflix_id, item_type)
    if not media_item:
        raise HTTPException(status_code=404, detail=f"Media item with Netflix ID '{netflix_id}' not found")

    dummy_media_mode = False
    try:
        dummy_media_mode = get_setting(db_path, "dummy_media_mode", "false").lower() in ("true", "1", "yes", "on")
    except Exception:
        pass

    nfo_data = find_and_parse_nfo(media_item)

    plot = nfo_data["plot"] or media_item.get("synopsis") or f"Top 10 Netflix content for {media_item.get('title')}."
    tagline = nfo_data["tagline"]
    maturity_rating = nfo_data["maturity_rating"] or media_item.get("maturity_rating")
    
    runtime_sec = nfo_data["runtime_seconds"] or media_item.get("runtime_seconds")
    formatted_runtime = None
    if runtime_sec and runtime_sec > 0:
        mins = runtime_sec // 60
        if mins >= 60:
            hrs = mins // 60
            rem_mins = mins % 60
            formatted_runtime = f"{hrs}h {rem_mins}m" if rem_mins else f"{hrs}h"
        else:
            formatted_runtime = f"{mins}m"

    studio = nfo_data["studio"] or "Netflix"

    details = {
        "plot": plot,
        "tagline": tagline,
        "maturity_rating": maturity_rating,
        "formatted_runtime": formatted_runtime,
        "studio": studio,
        "genres": nfo_data["genres"],
        "directors": nfo_data["directors"],
        "creators": nfo_data["creators"],
        "actors": nfo_data["actors"],
    }

    prev_item, next_item, item_rank, item_country_code, item_country_name = get_prev_next_media_items(
        db_path, media_item, target_country=country
    )

    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={
            "media_item": media_item,
            "details": details,
            "dummy_media_mode": dummy_media_mode,
            "prev_item": prev_item,
            "next_item": next_item,
            "item_rank": item_rank,
            "item_country_code": item_country_code,
            "item_country_name": item_country_name,
        }
    )

@app.get("/movie/{netflix_id}", response_class=HTMLResponse)
def movie_detail_page(request: Request, netflix_id: str, country: Optional[str] = Query(None)):
    return render_detail_page(request, netflix_id, "movie", country)

@app.get("/tv/{netflix_id}", response_class=HTMLResponse)
def tv_detail_page(request: Request, netflix_id: str, country: Optional[str] = Query(None)):
    return render_detail_page(request, netflix_id, "tv", country)

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
