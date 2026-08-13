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
    remove_monitored_country,
    calculate_expected_total_tasks,
    reset_stubs_and_failed_media_items,
    reset_zero_byte_media_stubs
)
from src.plex.auth import request_plex_pin, poll_plex_pin
from src.plex.sync import run_plex_sync
from src.scraper.netflix_top10 import crawl_netflix_top10
from src.scraper.tudum_downloader import download_pending_trailers
from src.cleanup import run_cleanup_cycle

from src.crawler_lock import (
    try_acquire_crawl_lock,
    release_crawl_lock,
    is_crawl_in_progress,
    set_crawl_progress,
    get_crawl_status_info
)

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

DEFAULT_DB_PATH = os.environ.get("NETPLEX_DB_PATH", "/config/netplex.db")

def get_db_path(request: Request) -> str:
    return getattr(request.app.state, "db_path", getattr(request.state, "db_path", DEFAULT_DB_PATH))

def run_crawl_pipeline(db_path: str):
    try:
        total_tasks = calculate_expected_total_tasks(db_path)
        set_crawl_progress(0, total_tasks, "Initiating crawl pipeline...")

        crawl_netflix_top10(db_path, total_tasks=total_tasks)
        
        conn = _get_connection(db_path)
        cursor = conn.execute("SELECT COUNT(*) as count FROM media_items WHERE status = 'pending'")
        new_pending = cursor.fetchone()['count']
        conn.close()
        
        total_tasks = max(total_tasks, new_pending)
        download_pending_trailers(db_path, total_tasks=total_tasks)


        conn = _get_connection(db_path)
        cursor = conn.execute("SELECT week FROM rankings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        latest_week = row["week"] if row else None
        conn.close()

        if latest_week:
            try:
                run_plex_sync(db_path, latest_week)
            except Exception as e:
                logger.error(f"Plex sync error during crawl: {e}")
            try:
                run_cleanup_cycle(db_path, latest_week)
            except Exception as e:
                logger.error(f"Cleanup cycle error during crawl: {e}")
    except Exception as e:
        logger.error(f"Crawl pipeline error: {e}")
    finally:
        release_crawl_lock()

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

from croniter import croniter

@router.get("/settings", response_class=HTMLResponse)
def get_settings_page(request: Request):
    db_path = get_db_path(request)
    
    plex_url = get_setting(db_path, "plex_url", "http://localhost:32400")
    plex_token = get_setting(db_path, "plex_token", "")
    cron_expression = get_setting(db_path, "cron_expression", "0 0 * * 2")
    dummy_media_mode = get_setting(db_path, "dummy_media_mode", "false").lower() in ("true", "1", "yes", "on")
    trailer_subtitles = get_setting(db_path, "trailer_subtitles", "false").lower() in ("true", "1", "yes", "on")
    subtitle_languages = get_setting(db_path, "subtitle_languages", "en")
    log_level = get_setting(db_path, "log_level", "INFO")
    
    monitored = get_monitored_countries(db_path)
    monitored_dict = {item["country_code"].upper(): item["formats"] for item in monitored}
    
    available_countries = [
        {"code": "GLOBAL", "name": "Global"},
        {"code": "AR", "name": "Argentina"},
        {"code": "AU", "name": "Australia"},
        {"code": "AT", "name": "Austria"},
        {"code": "BS", "name": "Bahamas"},
        {"code": "BH", "name": "Bahrain"},
        {"code": "BD", "name": "Bangladesh"},
        {"code": "BE", "name": "Belgium"},
        {"code": "BO", "name": "Bolivia"},
        {"code": "BR", "name": "Brazil"},
        {"code": "BG", "name": "Bulgaria"},
        {"code": "CA", "name": "Canada"},
        {"code": "CL", "name": "Chile"},
        {"code": "CO", "name": "Colombia"},
        {"code": "CR", "name": "Costa Rica"},
        {"code": "HR", "name": "Croatia"},
        {"code": "CY", "name": "Cyprus"},
        {"code": "CZ", "name": "Czech Republic"},
        {"code": "DK", "name": "Denmark"},
        {"code": "DO", "name": "Dominican Republic"},
        {"code": "EC", "name": "Ecuador"},
        {"code": "EG", "name": "Egypt"},
        {"code": "SV", "name": "El Salvador"},
        {"code": "EE", "name": "Estonia"},
        {"code": "FI", "name": "Finland"},
        {"code": "FR", "name": "France"},
        {"code": "DE", "name": "Germany"},
        {"code": "GR", "name": "Greece"},
        {"code": "GP", "name": "Guadeloupe"},
        {"code": "GT", "name": "Guatemala"},
        {"code": "HN", "name": "Honduras"},
        {"code": "HK", "name": "Hong Kong"},
        {"code": "HU", "name": "Hungary"},
        {"code": "IS", "name": "Iceland"},
        {"code": "IN", "name": "India"},
        {"code": "ID", "name": "Indonesia"},
        {"code": "IE", "name": "Ireland"},
        {"code": "IL", "name": "Israel"},
        {"code": "IT", "name": "Italy"},
        {"code": "JM", "name": "Jamaica"},
        {"code": "JP", "name": "Japan"},
        {"code": "JO", "name": "Jordan"},
        {"code": "KE", "name": "Kenya"},
        {"code": "KW", "name": "Kuwait"},
        {"code": "LV", "name": "Latvia"},
        {"code": "LB", "name": "Lebanon"},
        {"code": "LT", "name": "Lithuania"},
        {"code": "LU", "name": "Luxembourg"},
        {"code": "MY", "name": "Malaysia"},
        {"code": "MV", "name": "Maldives"},
        {"code": "MT", "name": "Malta"},
        {"code": "MQ", "name": "Martinique"},
        {"code": "MU", "name": "Mauritius"},
        {"code": "MX", "name": "Mexico"},
        {"code": "MA", "name": "Morocco"},
        {"code": "NL", "name": "Netherlands"},
        {"code": "NC", "name": "New Caledonia"},
        {"code": "NZ", "name": "New Zealand"},
        {"code": "NI", "name": "Nicaragua"},
        {"code": "NG", "name": "Nigeria"},
        {"code": "NO", "name": "Norway"},
        {"code": "OM", "name": "Oman"},
        {"code": "PK", "name": "Pakistan"},
        {"code": "PA", "name": "Panama"},
        {"code": "PY", "name": "Paraguay"},
        {"code": "PE", "name": "Peru"},
        {"code": "PH", "name": "Philippines"},
        {"code": "PL", "name": "Poland"},
        {"code": "PT", "name": "Portugal"},
        {"code": "QA", "name": "Qatar"},
        {"code": "RO", "name": "Romania"},
        {"code": "RE", "name": "Réunion"},
        {"code": "SA", "name": "Saudi Arabia"},
        {"code": "RS", "name": "Serbia"},
        {"code": "SG", "name": "Singapore"},
        {"code": "SK", "name": "Slovakia"},
        {"code": "SI", "name": "Slovenia"},
        {"code": "ZA", "name": "South Africa"},
        {"code": "KR", "name": "South Korea"},
        {"code": "ES", "name": "Spain"},
        {"code": "LK", "name": "Sri Lanka"},
        {"code": "SE", "name": "Sweden"},
        {"code": "CH", "name": "Switzerland"},
        {"code": "TW", "name": "Taiwan"},
        {"code": "TH", "name": "Thailand"},
        {"code": "TT", "name": "Trinidad and Tobago"},
        {"code": "TR", "name": "Türkiye"},
        {"code": "UA", "name": "Ukraine"},
        {"code": "AE", "name": "United Arab Emirates"},
        {"code": "GB", "name": "United Kingdom"},
        {"code": "US", "name": "United States"},
        {"code": "UY", "name": "Uruguay"},
        {"code": "VE", "name": "Venezuela"},
        {"code": "VN", "name": "Vietnam"},
    ]
    
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "plex_url": plex_url,
            "plex_token": plex_token,
            "cron_expression": cron_expression,
            "dummy_media_mode": dummy_media_mode,
            "trailer_subtitles": trailer_subtitles,
            "subtitle_languages": subtitle_languages,
            "monitored_dict": monitored_dict,
            "monitored_countries": monitored,
            "available_countries": available_countries,
            "success": request.query_params.get("success") == "1"
        }
    )

@router.post("/settings")
@router.post("/api/settings")
async def save_settings(request: Request, background_tasks: BackgroundTasks):
    db_path = get_db_path(request)
    content_type = request.headers.get("content-type", "")
    
    if "application/json" in content_type:
        data = await request.json()
        plex_url = data.get("plex_url")
        plex_token = data.get("plex_token")
        cron_expression = data.get("cron_expression")
        dummy_media_mode = data.get("dummy_media_mode")
        trailer_subtitles = data.get("trailer_subtitles")
        subtitle_languages = data.get("subtitle_languages")
        log_level = data.get("log_level")
        monitored_countries = data.get("monitored_countries")
    else:
        form_dict = await parse_form_data(request)
        plex_url = form_dict.get("plex_url", [None])[0]
        plex_token = form_dict.get("plex_token", [None])[0]
        cron_expression = form_dict.get("cron_expression", [None])[0]
        dummy_media_mode = form_dict.get("dummy_media_mode", [None])[0]
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

    if cron_expression is not None:
        if not croniter.is_valid(str(cron_expression)):
            raise HTTPException(status_code=400, detail="Invalid cron expression")
        set_setting(db_path, "cron_expression", str(cron_expression))

    if plex_url is not None:
        set_setting(db_path, "plex_url", str(plex_url))
    if plex_token is not None:
        set_setting(db_path, "plex_token", str(plex_token))
    
    dummy_mode_deactivated = False
    if dummy_media_mode is not None:
        prev_val = get_setting(db_path, "dummy_media_mode", "false").lower() in ("true", "1", "yes", "on")
        val = "true" if str(dummy_media_mode).lower() in ("true", "1", "on", "yes") else "false"
        set_setting(db_path, "dummy_media_mode", val)
        new_val = (val == "true")
        if prev_val and not new_val:
            dummy_mode_deactivated = True

    if trailer_subtitles is not None:
        val = "true" if str(trailer_subtitles).lower() in ("true", "1", "on", "yes") else "false"
        set_setting(db_path, "trailer_subtitles", val)
    if subtitle_languages is not None:
        set_setting(db_path, "subtitle_languages", str(subtitle_languages))
    if log_level is not None:
        set_setting(db_path, "log_level", str(log_level))


    region_changed = False
    if monitored_countries is not None:
        existing = get_monitored_countries(db_path)
        existing_map = {item["country_code"].upper(): item.get("formats", "movie,tv") for item in existing}
        
        new_map = {}
        for item in monitored_countries:
            if isinstance(item, dict):
                code = item.get("country_code")
                formats = item.get("formats", "movie,tv")
            else:
                code = str(item)
                formats = "movie,tv"
            if code:
                new_map[code.upper()] = formats

        if existing_map != new_map:
            region_changed = True
            for item in existing:
                remove_monitored_country(db_path, item["country_code"])
                
            for code, formats in new_map.items():
                set_monitored_country(db_path, code, formats)

    # Check for zero-byte media stubs or failed items if dummy mode is inactive
    dummy_mode_active = get_setting(db_path, "dummy_media_mode", "false").lower() in ("true", "1", "yes", "on")
    stubs_reset_count = 0
    if not dummy_mode_active:
        reset_ids = reset_stubs_and_failed_media_items(db_path)
        stubs_reset_count = len(reset_ids)

    # Auto-trigger crawler if region configuration changed or dummy mode deactivated / zero-byte stubs reset
    should_trigger_crawl = region_changed or dummy_mode_deactivated or (stubs_reset_count > 0)
    if should_trigger_crawl and not is_crawl_in_progress():
        if try_acquire_crawl_lock():
            background_tasks.add_task(run_crawl_pipeline, db_path)

    if "application/json" in content_type:
        return JSONResponse({"status": "success", "message": "Settings updated successfully", "crawl_triggered": should_trigger_crawl})
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

@router.post("/api/crawl", status_code=202)
def trigger_manual_crawl(request: Request, background_tasks: BackgroundTasks):
    if not try_acquire_crawl_lock():
        raise HTTPException(status_code=409, detail="A crawl job is already in progress")

    db_path = get_db_path(request)
    background_tasks.add_task(run_crawl_pipeline, db_path)
    return JSONResponse(status_code=202, content={"status": "accepted", "message": "Crawl pipeline initiated"})

@router.get("/api/crawl/status")
def get_crawl_status():
    return JSONResponse(get_crawl_status_info())

