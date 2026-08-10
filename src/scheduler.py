import os
import time
import signal
import logging
from datetime import datetime, timezone
from typing import Optional

from src.database import _get_connection, get_setting, set_setting
from src.scraper.netflix_top10 import crawl_netflix_top10
from src.scraper.tudum_downloader import download_pending_trailers
from src.cleanup import run_cleanup_cycle
from src.plex.sync import run_plex_sync
from src.logger import get_logger

logger = get_logger("netplex.scheduler")
_running = True

def get_latest_week(db_path: str) -> Optional[str]:
    """Queries SQLite database to return the latest week string from rankings."""
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("SELECT week FROM rankings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return row["week"] if row else None
    finally:
        conn.close()

def prune_orphans(db_path: str) -> dict:
    """Executes cleanup cycle for orphaned media items from the latest week."""
    latest_week = get_latest_week(db_path)
    if not latest_week:
        logger.info("No rankings found. Skipping orphan pruning.")
        return {"orphans_found": 0, "folders_deleted": 0, "records_pruned": 0}
    return run_cleanup_cycle(db_path, latest_week)

def sync_plex_collections(db_path: str) -> bool:
    """Wraps Plex collection synchronization in safe connection exception handling."""
    latest_week = get_latest_week(db_path)
    if not latest_week:
        logger.info("No rankings found. Skipping Plex collection sync.")
        return False
    try:
        return run_plex_sync(db_path, latest_week)
    except Exception as e:
        logger.error(f"Plex collection sync failed: {e}")
        return False

def run_full_sync_pipeline(db_path: str) -> dict:
    """
    Executes full synchronization pipeline in order:
    1. Crawl Top 10 data from Netflix Tudum
    2. Download pending trailer assets
    3. Prune orphaned local files
    4. Sync Plex server collections
    5. Record last_crawl_timestamp
    """
    logger.info("Starting full NetPlex sync pipeline...")
    results = {}
    
    logger.info("Step 1: Crawling Netflix Top 10 rankings...")
    crawl_netflix_top10(db_path)
    results["step1"] = "completed"
    
    logger.info("Step 2: Downloading pending trailers...")
    download_pending_trailers(db_path)
    results["step2"] = "completed"
    
    logger.info("Step 3: Pruning orphaned media...")
    cleanup_res = prune_orphans(db_path)
    results["step3"] = cleanup_res
    
    logger.info("Step 4: Syncing Plex collections...")
    plex_res = sync_plex_collections(db_path)
    results["step4"] = plex_res
    
    now_iso = datetime.now(timezone.utc).isoformat()
    set_setting(db_path, "last_crawl_timestamp", now_iso)
    logger.info(f"Full sync pipeline completed successfully at {now_iso}.")
    
    return results

def should_run_sync(db_path: str) -> bool:
    """Determines whether a sync pipeline execution is due based on DB timestamp and interval."""
    last_crawl = get_setting(db_path, "last_crawl_timestamp")
    if not last_crawl:
        return True
    try:
        last_dt = datetime.fromisoformat(last_crawl)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
            
        interval_str = get_setting(db_path, "update_interval_hours", "168")
        interval_hours = float(interval_str)
        
        now = datetime.now(timezone.utc)
        elapsed_seconds = (now - last_dt).total_seconds()
        return elapsed_seconds >= interval_hours * 3600
    except Exception as e:
        logger.error(f"Error parsing sync timestamp or interval: {e}")
        return True

def handle_shutdown_signal(signum, frame):
    """Signal handler for graceful shutdown on SIGINT / SIGTERM."""
    global _running
    logger.info(f"Received termination signal ({signum}). Shutting down scheduler gracefully...")
    _running = False

def start_scheduler(db_path: str = "/config/netplex.db", poll_interval: int = 60, run_once: bool = False):
    """
    Main loop for background daemon scheduler. Checks sync eligibility periodically
    and triggers full sync pipeline execution.
    """
    global _running
    _running = True
    
    try:
        signal.signal(signal.SIGINT, handle_shutdown_signal)
        signal.signal(signal.SIGTERM, handle_shutdown_signal)
    except (ValueError, AttributeError):
        pass

    logger.info(f"NetPlex daemon scheduler started (poll_interval={poll_interval}s, db_path='{db_path}').")
    
    while _running:
        if should_run_sync(db_path):
            try:
                run_full_sync_pipeline(db_path)
            except Exception as e:
                logger.error(f"Error during full sync pipeline execution: {e}")
                
        if run_once or not _running:
            break
            
        time.sleep(poll_interval)

    logger.info("Daemon scheduler stopped.")
