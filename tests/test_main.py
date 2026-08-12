import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

import main

def test_main_initialization(tmp_path):
    db_file = str(tmp_path / "test_main.db")
    config_dir = str(tmp_path / "config")
    
    with patch.dict(os.environ, {
        "NETPLEX_DB_PATH": db_file,
        "NETPLEX_CONFIG_DIR": config_dir,
        "NETPLEX_PORT": "8999"
    }):
        # Mock start_scheduler/run_server so main runs once
        with patch("main.start_scheduler") as mock_sched, \
             patch("main.run_server") as mock_server:
            
            mock_server.return_value = None
            mock_sched.return_value = None
            
            # Verify init_db creates schema
            main.init_db(db_file)
            assert os.path.exists(db_file)
            
            conn = sqlite3.connect(db_file)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            assert "settings" in tables
            assert "media_items" in tables
            assert "rankings" in tables
