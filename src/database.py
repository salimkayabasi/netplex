import os
import sqlite3
import uuid

def _get_connection(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        # Ensure parent directory exists
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Enforce foreign key constraints
    conn.execute("PRAGMA foreign_keys = ON;")
    if db_path != ":memory:":
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
        except sqlite3.OperationalError:
            # Fallback if WAL is not supported or cannot be initialized
            pass
    return conn

def init_db(db_path: str = "/config/netplex.db"):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS monitored_countries (
                    country_code TEXT PRIMARY KEY,
                    formats TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS media_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL CHECK (type IN ('movie', 'tv')),
                    release_year INTEGER NOT NULL,
                    season_name TEXT,
                    folder_name TEXT NOT NULL,
                    file_path TEXT,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'downloaded', 'failed')),
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(title, type, release_year, season_name)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    category TEXT NOT NULL CHECK (category IN ('Films', 'TV')),
                    rank INTEGER NOT NULL CHECK (rank >= 1 AND rank <= 10),
                    week TEXT NOT NULL,
                    media_item_id INTEGER NOT NULL,
                    FOREIGN KEY (media_item_id) REFERENCES media_items(id) ON DELETE CASCADE
                )
            """)
            
            # Seed default configurations
            defaults = [
                ('update_interval_hours', '168'),
                ('log_level', 'INFO'),
                ('trailer_subtitles', 'false'),
                ('subtitle_languages', 'en')
            ]
            for key, val in defaults:
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, val)
                )

            # Ensure unique Plex client UUID exists
            cursor = conn.execute("SELECT value FROM settings WHERE key = 'plex_client_id'")
            if not cursor.fetchone():
                client_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('plex_client_id', ?)",
                    (client_id,)
                )
    finally:
        conn.close()

def get_setting(db_path: str, key: str, default: str | None = None) -> str | None:
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row['value']
        return default
    finally:
        conn.close()

def set_setting(db_path: str, key: str, value: str):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
    finally:
        conn.close()

def get_monitored_countries(db_path: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("SELECT country_code, formats FROM monitored_countries")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def set_monitored_country(db_path: str, country_code: str, formats: str):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO monitored_countries (country_code, formats) VALUES (?, ?)",
                (country_code, formats)
            )
    finally:
        conn.close()

def remove_monitored_country(db_path: str, country_code: str):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM monitored_countries WHERE country_code = ?", (country_code,))
    finally:
        conn.close()

def upsert_media_item(db_path: str, title: str, type: str, release_year: int, season_name: str | None, folder_name: str) -> int:
    conn = _get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "SELECT id FROM media_items WHERE title = ? AND type = ? AND release_year = ? AND season_name IS ?",
                (title, type, release_year, season_name)
            )
            row = cursor.fetchone()
            if row:
                media_item_id = row['id']
                conn.execute(
                    "UPDATE media_items SET last_seen_at = CURRENT_TIMESTAMP, folder_name = ? WHERE id = ?",
                    (folder_name, media_item_id)
                )
                return media_item_id
            else:
                cursor = conn.execute(
                    "INSERT INTO media_items (title, type, release_year, season_name, folder_name, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                    (title, type, release_year, season_name, folder_name)
                )
                return cursor.lastrowid
    finally:
        conn.close()

def update_media_item_status(db_path: str, item_id: int, status: str, file_path: str | None = None):
    conn = _get_connection(db_path)
    try:
        with conn:
            if file_path is not None:
                conn.execute(
                    "UPDATE media_items SET status = ?, file_path = ? WHERE id = ?",
                    (status, file_path, item_id)
                )
            else:
                conn.execute(
                    "UPDATE media_items SET status = ? WHERE id = ?",
                    (status, item_id)
                )
    finally:
        conn.close()

def clear_rankings_for_week(db_path: str, week: str):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM rankings WHERE week = ?", (week,))
    finally:
        conn.close()

def insert_ranking(db_path: str, country_code: str, category: str, rank: int, week: str, media_item_id: int):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO rankings (country_code, category, rank, week, media_item_id) VALUES (?, ?, ?, ?, ?)",
                (country_code, category, rank, week, media_item_id)
            )
    finally:
        conn.close()

def get_active_rankings(db_path: str, country_code: str, category: str, week: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT 
                r.id AS ranking_id, r.country_code, r.category, r.rank, r.week,
                m.id AS media_item_id, m.title, m.type, m.release_year, m.season_name, m.folder_name, m.file_path, m.status, m.added_at, m.last_seen_at
            FROM rankings r
            JOIN media_items m ON r.media_item_id = m.id
            WHERE r.country_code = ? AND r.category = ? AND r.week = ?
            ORDER BY r.rank ASC
        """, (country_code, category, week))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_orphaned_media_items(db_path: str, current_week: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT id, title, type, release_year, season_name, folder_name, file_path, status, added_at, last_seen_at
            FROM media_items
            WHERE id NOT IN (
                SELECT DISTINCT media_item_id 
                FROM rankings 
                WHERE week = ?
            )
        """, (current_week,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
