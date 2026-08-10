import os
import json
import logging
import threading
import urllib.parse
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.database import (
    _get_connection,
    get_setting,
    set_setting,
    get_monitored_countries,
    set_monitored_country,
    remove_monitored_country
)
from src.plex.auth import request_plex_pin, poll_plex_pin
from src.plex.sync import run_plex_sync
from src.scraper.netflix_top10 import crawl_netflix_top10
from src.scraper.tudum_downloader import download_pending_trailers
from src.cleanup import run_cleanup_cycle

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DEFAULT_DB_PATH = os.environ.get("NETPLEX_DB_PATH", "/config/netplex.db")

def get_db_path(request: Request) -> str:
    return getattr(request.app.state, "db_path", getattr(request.state, "db_path", DEFAULT_DB_PATH))

IS_CRAWLING = False
crawling_lock = threading.Lock()

async def parse_form_data(request: Request) -> dict[str, list[str]]:
    try:
        form = await request.form()
        res = {}
        for k in form.keys():
            res[k] = form.getlist(k)
        return res
    except Exception:
        body = await request.body()
        parsed = urllib.parse.parse_qs(body.decode("utf-8"))
        return parsed

@router.get("/settings", response_class=HTMLResponse)
def get_settings_page(request: Request):
    db_path = get_db_path(request)
    
    plex_url = get_setting(db_path, "plex_url", "http://localhost:32400")
    plex_token = get_setting(db_path, "plex_token", "")
    update_interval = get_setting(db_path, "update_interval_hours", "168")
    trailer_subtitles = get_setting(db_path, "trailer_subtitles", "false").lower() in ("true", "1", "yes", "on")
    subtitle_languages = get_setting(db_path, "subtitle_languages", "en")
    log_level = get_setting(db_path, "log_level", "INFO")
    
    monitored = get_monitored_countries(db_path)
    monitored_dict = {item["country_code"].upper(): item["formats"] for item in monitored}
    
    available_countries = [
        {"code": "GLOBAL", "name": "Global Top 10"},
        {"code": "US", "name": "United States"},
        {"code": "GB", "name": "United Kingdom"},
        {"code": "CA", "name": "Canada"},
        {"code": "AU", "name": "Australia"},
        {"code": "DE", "name": "Germany"},
        {"code": "FR", "name": "France"},
        {"code": "ES", "name": "Spain"},
        {"code": "IT", "name": "Italy"},
        {"code": "JP", "name": "Japan"},
        {"code": "KR", "name": "South Korea"},
        {"code": "BR", "name": "Brazil"},
        {"code": "MX", "name": "Mexico"},
        {"code": "IN", "name": "India"},
        {"code": "TR", "name": "Turkey"},
    ]
    
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "plex_url": plex_url,
            "plex_token": plex_token,
            "update_interval": update_interval,
            "trailer_subtitles": trailer_subtitles,
            "subtitle_languages": subtitle_languages,
            "log_level": log_level,
            "monitored_dict": monitored_dict,
            "monitored_countries": monitored,
            "available_countries": available_countries,
            "success": request.query_params.get("success") == "1"
        }
    )

@router.post("/settings")
@router.post("/api/settings")
async def save_settings(request: Request):
    db_path = get_db_path(request)
    content_type = request.headers.get("content-type", "")
    
    if "application/json" in content_type:
        data = await request.json()
        plex_url = data.get("plex_url")
        plex_token = data.get("plex_token")
        update_interval_hours = data.get("update_interval_hours")
        trailer_subtitles = data.get("trailer_subtitles")
        subtitle_languages = data.get("subtitle_languages")
        log_level = data.get("log_level")
        monitored_countries = data.get("monitored_countries")
    else:
        form_dict = await parse_form_data(request)
        plex_url = form_dict.get("plex_url", [None])[0]
        plex_token = form_dict.get("plex_token", [None])[0]
        update_interval_hours = form_dict.get("update_interval_hours", [None])[0]
        trailer_subtitles = form_dict.get("trailer_subtitles", [None])[0]
        subtitle_languages = form_dict.get("subtitle_languages", [None])[0]
        log_level = form_dict.get("log_level", [None])[0]
        
        country_codes = form_dict.get("country_code", [])
        monitored_countries = []
        for code in country_codes:
            movie_chk = form_dict.get(f"format_movie_{code}")
            tv_chk = form_dict.get(f"format_tv_{code}")
            fmt_parts = []
            if movie_chk:
                fmt_parts.append("movie")
            if tv_chk:
                fmt_parts.append("tv")
            fmt_str = ",".join(fmt_parts) if fmt_parts else "movie,tv"
            monitored_countries.append({"country_code": code, "formats": fmt_str})

    if plex_url is not None:
        set_setting(db_path, "plex_url", str(plex_url))
    if plex_token is not None:
        set_setting(db_path, "plex_token", str(plex_token))
    if update_interval_hours is not None:
        set_setting(db_path, "update_interval_hours", str(update_interval_hours))
    if trailer_subtitles is not None:
        val = "true" if str(trailer_subtitles).lower() in ("true", "1", "on", "yes") else "false"
        set_setting(db_path, "trailer_subtitles", val)
    if subtitle_languages is not None:
        set_setting(db_path, "subtitle_languages", str(subtitle_languages))
    if log_level is not None:
        set_setting(db_path, "log_level", str(log_level))

    if monitored_countries is not None:
        existing = get_monitored_countries(db_path)
        for item in existing:
            remove_monitored_country(db_path, item["country_code"])
            
        for item in monitored_countries:
            if isinstance(item, dict):
                code = item.get("country_code")
                formats = item.get("formats", "movie,tv")
            else:
                code = str(item)
                formats = "movie,tv"
            if code:
                set_monitored_country(db_path, code.upper(), formats)

    if "application/json" in content_type:
        return JSONResponse({"status": "success", "message": "Settings updated successfully"})
    else:
        return RedirectResponse(url="/settings?success=1", status_code=303)

@router.post("/api/auth/plex/pin")
def get_plex_pin(request: Request):
    db_path = get_db_path(request)
    try:
        pin_data = request_plex_pin(db_path)
        return JSONResponse(pin_data)
    except Exception as e:
        logger.error(f"Error requesting Plex PIN: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/auth/plex/status/{pin_id}")
def check_plex_pin_status(request: Request, pin_id: str):
    db_path = get_db_path(request)
    auth_token = poll_plex_pin(db_path, pin_id)
    if auth_token:
        return JSONResponse({"authorized": True, "token": auth_token})
    return JSONResponse({"authorized": False})

@router.get("/api/logs")
def get_application_logs(request: Request, max_lines: int = Query(100, ge=1, le=1000)):
    log_path = getattr(request.app.state, "log_path", os.environ.get("NETPLEX_LOG_FILE", "/config/netplex.log"))
    abs_log_path = os.path.abspath(log_path)
    
    config_dir = getattr(request.app.state, "config_dir", os.environ.get("NETPLEX_CONFIG_DIR", os.path.dirname(abs_log_path) or "/config"))
    allowed_dir = os.path.abspath(config_dir)
    
    try:
        common = os.path.commonpath([abs_log_path, allowed_dir])
        if common != allowed_dir and not abs_log_path.startswith(allowed_dir):
            raise HTTPException(status_code=403, detail="Access outside allowed log directory is forbidden")
    except Exception:
        raise HTTPException(status_code=403, detail="Access outside allowed log directory is forbidden")

    if not os.path.exists(abs_log_path):
        return JSONResponse({"lines": [], "content": ""})

    try:
        with open(abs_log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            last_lines = [line.rstrip("\r\n") for line in lines[-max_lines:]]
            return JSONResponse({
                "lines": last_lines,
                "content": "\n".join(last_lines)
            })
    except Exception as e:
        logger.error(f"Error reading log file {abs_log_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read log file")

@router.post("/api/crawl", status_code=202)
def trigger_manual_crawl(request: Request, background_tasks: BackgroundTasks):
    global IS_CRAWLING
    with crawling_lock:
        if IS_CRAWLING:
            raise HTTPException(status_code=409, detail="A crawl job is already in progress")
        IS_CRAWLING = True

    db_path = get_db_path(request)

    def task_wrapper():
        global IS_CRAWLING
        try:
            crawl_netflix_top10(db_path)
            download_pending_trailers(db_path)
            
            conn = _get_connection(db_path)
            cursor = conn.execute("SELECT week FROM rankings ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            latest_week = row["week"] if row else None
            conn.close()
            
            if latest_week:
                try:
                    run_plex_sync(db_path, latest_week)
                except Exception as e:
                    logger.error(f"Plex sync error during manual crawl: {e}")
                try:
                    run_cleanup_cycle(db_path, latest_week)
                except Exception as e:
                    logger.error(f"Cleanup cycle error during manual crawl: {e}")
        except Exception as e:
            logger.error(f"Manual crawl pipeline error: {e}")
        finally:
            with crawling_lock:
                IS_CRAWLING = False

    background_tasks.add_task(task_wrapper)
    return JSONResponse(status_code=202, content={"status": "accepted", "message": "Crawl pipeline initiated"})

@router.get("/api/crawl/status")
def get_crawl_status():
    global IS_CRAWLING
    with crawling_lock:
        return JSONResponse({"is_crawling": IS_CRAWLING})
