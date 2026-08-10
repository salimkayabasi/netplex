import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from src.database import init_db, get_setting, set_setting
from src.logger import setup_logger, get_logger
from src.scheduler import (
    prune_orphans,
    sync_plex_collections,
    run_full_sync_pipeline,
    should_run_sync,
    handle_shutdown_signal,
    start_scheduler,
    _running
)

def test_setup_logger_creates_handlers_and_directory(tmp_path):
    log_dir = tmp_path / "logs"
    log_file = log_dir / "netplex.log"
    
    assert not log_dir.exists()
    
    logger = setup_logger(log_level="DEBUG", log_file=str(log_file))
    
    assert log_dir.exists()
    assert log_file.exists()
    assert logger.level == logging.DEBUG
    
    # Handlers should include StreamHandler and RotatingFileHandler
    handler_types = [type(h) for h in logger.handlers]
    assert logging.StreamHandler in handler_types
    assert logging.handlers.RotatingFileHandler in handler_types
    
    # Write a test log entry
    test_message = "Test log entry message 12345"
    logger.debug(test_message)
    
    # Close handlers to flush
    for h in logger.handlers:
        h.close()
        
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert test_message in content

def test_setup_logger_prevents_duplicate_handlers(tmp_path):
    log_file = tmp_path / "test.log"
    setup_logger(log_file=str(log_file))
    initial_count = len(logging.getLogger("netplex").handlers)
    
    # Call setup_logger a second time
    setup_logger(log_file=str(log_file))
    second_count = len(logging.getLogger("netplex").handlers)
    
    assert initial_count == second_count

@patch("src.scheduler.sync_plex_collections")
@patch("src.scheduler.prune_orphans")
@patch("src.scheduler.download_pending_trailers")
@patch("src.scheduler.crawl_netflix_top10")
def test_run_full_sync_pipeline_sequence(
    mock_crawl, mock_download, mock_prune, mock_sync, tmp_path
):
    db_path = str(tmp_path / "test_pipeline.db")
    init_db(db_path)
    
    mock_prune.return_value = {"orphans_found": 0, "folders_deleted": 0, "records_pruned": 0}
    mock_sync.return_value = True
    
    execution_order = []

    def side_effect_crawl(path):
        execution_order.append("crawl")

    def side_effect_download(path):
        execution_order.append("download")

    def side_effect_prune(path):
        execution_order.append("prune")
        return {"orphans_found": 0, "folders_deleted": 0, "records_pruned": 0}

    def side_effect_sync(path):
        execution_order.append("sync")
        return True

    mock_crawl.side_effect = side_effect_crawl
    mock_download.side_effect = side_effect_download
    mock_prune.side_effect = side_effect_prune
    mock_sync.side_effect = side_effect_sync
    
    res = run_full_sync_pipeline(db_path)
    
    assert execution_order == ["crawl", "download", "prune", "sync"]
    assert res["step1"] == "completed"
    assert res["step2"] == "completed"
    assert res["step4"] is True
    
    # Timestamp recorded in database
    ts = get_setting(db_path, "last_crawl_timestamp")
    assert ts is not None
    # Parse timestamp to ensure valid ISO format
    dt = datetime.fromisoformat(ts)
    assert dt is not None

def test_prune_orphans_no_week(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_db(db_path)
    
    res = prune_orphans(db_path)
    assert res == {"orphans_found": 0, "folders_deleted": 0, "records_pruned": 0}

@patch("src.scheduler.run_plex_sync")
@patch("src.scheduler.get_latest_week")
def test_sync_plex_collections_exception_handling(mock_get_week, mock_run_sync, tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    mock_get_week.return_value = "2026-W32"
    mock_run_sync.side_effect = Exception("Plex connection timed out")
    
    result = sync_plex_collections(db_path)
    assert result is False

def test_should_run_sync_no_timestamp(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    assert should_run_sync(db_path) is True

def test_should_run_sync_recently_run(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    
    recent_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    set_setting(db_path, "last_crawl_timestamp", recent_ts)
    set_setting(db_path, "update_interval_hours", "24")
    
    assert should_run_sync(db_path) is False

def test_should_run_sync_due(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    
    past_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    set_setting(db_path, "last_crawl_timestamp", past_ts)
    set_setting(db_path, "update_interval_hours", "24")
    
    assert should_run_sync(db_path) is True

def test_handle_shutdown_signal():
    import src.scheduler as sched
    sched._running = True
    handle_shutdown_signal(15, None)
    assert sched._running is False

@patch("src.scheduler.run_full_sync_pipeline")
def test_start_scheduler_run_once(mock_pipeline, tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    
    start_scheduler(db_path=db_path, poll_interval=1, run_once=True)
    mock_pipeline.assert_called_once_with(db_path)
