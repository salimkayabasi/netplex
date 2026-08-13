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
                    local_title TEXT,
                    show_title TEXT,
                    season_title TEXT,
                    type TEXT NOT NULL CHECK (type IN ('movie', 'tv')),
                    release_year INTEGER NOT NULL,
                    season_name TEXT,
                    folder_name TEXT NOT NULL,
                    file_path TEXT,
                    poster_url TEXT,
                    logo_url TEXT,
                    video_url TEXT,
                    subtitle_url TEXT,
                    youtube_url TEXT,
                    netflix_id INTEGER,
                    synopsis TEXT,
                    maturity_rating TEXT,
                    runtime_seconds INTEGER,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'downloaded', 'failed')),
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(title, type, release_year, season_name)
                )
            """)
            # Check for existing DBs and migrate missing columns
            cursor = conn.execute("PRAGMA table_info(media_items)")
            columns = [row['name'] for row in cursor.fetchall()]
            new_media_cols = {
                'poster_url': 'TEXT',
                'local_title': 'TEXT',
                'show_title': 'TEXT',
                'season_title': 'TEXT',
                'logo_url': 'TEXT',
                'video_url': 'TEXT',
                'subtitle_url': 'TEXT',
                'youtube_url': 'TEXT',
                'netflix_id': 'INTEGER',
                'synopsis': 'TEXT',
                'maturity_rating': 'TEXT',
                'runtime_seconds': 'INTEGER'
            }
            for col_name, col_type in new_media_cols.items():
                if col_name not in columns:
                    conn.execute(f"ALTER TABLE media_items ADD COLUMN {col_name} {col_type}")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS rankings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    country_code TEXT NOT NULL,
                    country_name TEXT,
                    category TEXT NOT NULL CHECK (category IN ('Movies', 'TV')),
                    rank INTEGER NOT NULL CHECK (rank >= 1 AND rank <= 10),
                    week TEXT NOT NULL,
                    weekly_hours_viewed INTEGER,
                    weekly_views INTEGER,
                    cumulative_weeks_in_top_10 INTEGER,
                    media_item_id INTEGER NOT NULL,
                    FOREIGN KEY (media_item_id) REFERENCES media_items(id) ON DELETE CASCADE
                )
            """)
            cursor = conn.execute("PRAGMA table_info(rankings)")
            r_columns = [row['name'] for row in cursor.fetchall()]
            new_ranking_cols = {
                'country_name': 'TEXT',
                'weekly_hours_viewed': 'INTEGER',
                'weekly_views': 'INTEGER',
                'cumulative_weeks_in_top_10': 'INTEGER'
            }
            for col_name, col_type in new_ranking_cols.items():
                if col_name not in r_columns:
                    conn.execute(f"ALTER TABLE rankings ADD COLUMN {col_name} {col_type}")
            
            # Seed default configurations
            defaults = [
                ('cron_expression', '0 0 * * 2'),
                ('dummy_media_mode', 'false'),
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

            # Truncate media items and rankings if no monitored countries exist (first boot / no config set)
            cursor = conn.execute("SELECT COUNT(*) as count FROM monitored_countries")
            if cursor.fetchone()['count'] == 0:
                conn.execute("DELETE FROM rankings")
                conn.execute("DELETE FROM media_items")
    finally:
        conn.close()

def truncate_database(db_path: str):
    """Truncates rankings and media_items tables from database."""
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM rankings")
            conn.execute("DELETE FROM media_items")
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
        cursor = conn.execute("SELECT country_code, formats FROM monitored_countries ORDER BY rowid ASC")
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

def upsert_media_item(
    db_path: str,
    title: str,
    type: str,
    release_year: int,
    season_name: str | None,
    folder_name: str,
    local_title: str | None = None,
    netflix_id: int | str | None = None,
    show_title: str | None = None,
    season_title: str | None = None,
    synopsis: str | None = None,
    maturity_rating: str | None = None,
    runtime_seconds: int | None = None,
    logo_url: str | None = None,
    video_url: str | None = None,
    subtitle_url: str | None = None,
    poster_url: str | None = None,
    youtube_url: str | None = None
) -> int:
    conn = _get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "SELECT id FROM media_items WHERE title = ? AND type = ? AND release_year = ? AND season_name IS ?",
                (title, type, release_year, season_name)
            )
            row = cursor.fetchone()
            kwargs = {
                'local_title': local_title,
                'netflix_id': int(netflix_id) if netflix_id and str(netflix_id).isdigit() else netflix_id,
                'show_title': show_title,
                'season_title': season_title,
                'synopsis': synopsis,
                'maturity_rating': maturity_rating,
                'runtime_seconds': runtime_seconds,
                'logo_url': logo_url,
                'video_url': video_url,
                'subtitle_url': subtitle_url,
                'poster_url': poster_url,
                'youtube_url': youtube_url
            }
            if row:
                media_item_id = row['id']
                updates = ["last_seen_at = CURRENT_TIMESTAMP", "folder_name = ?"]
                params = [folder_name]
                for key, val in kwargs.items():
                    if val is not None:
                        updates.append(f"{key} = ?")
                        params.append(val)
                params.append(media_item_id)
                conn.execute(
                    f"UPDATE media_items SET {', '.join(updates)} WHERE id = ?",
                    tuple(params)
                )
                return media_item_id
            else:
                fields = ['title', 'type', 'release_year', 'season_name', 'folder_name', 'status']
                placeholders = ['?', '?', '?', '?', '?', "'pending'"]
                params = [title, type, release_year, season_name, folder_name]
                for key, val in kwargs.items():
                    if val is not None:
                        fields.append(key)
                        placeholders.append('?')
                        params.append(val)
                cursor = conn.execute(
                    f"INSERT INTO media_items ({', '.join(fields)}) VALUES ({', '.join(placeholders)})",
                    tuple(params)
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

def update_media_item_poster(db_path: str, item_id: int, poster_url: str):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE media_items SET poster_url = ? WHERE id = ?",
                (poster_url, item_id)
            )
    finally:
        conn.close()

def update_media_item_local_title(db_path: str, item_id: int, local_title: str):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE media_items SET local_title = ? WHERE id = ?",
                (local_title, item_id)
            )
    finally:
        conn.close()

def update_media_item_tudum_metadata(
    db_path: str,
    item_id: int,
    synopsis: str | None = None,
    video_url: str | None = None,
    subtitle_url: str | None = None,
    netflix_id: int | str | None = None,
    poster_url: str | None = None,
    logo_url: str | None = None,
    maturity_rating: str | None = None,
    runtime_seconds: int | None = None,
    youtube_url: str | None = None
):
    conn = _get_connection(db_path)
    try:
        with conn:
            updates = []
            params = []
            kwargs = {
                'synopsis': synopsis,
                'video_url': video_url,
                'subtitle_url': subtitle_url,
                'netflix_id': int(netflix_id) if netflix_id and str(netflix_id).isdigit() else netflix_id,
                'poster_url': poster_url,
                'logo_url': logo_url,
                'maturity_rating': maturity_rating,
                'runtime_seconds': runtime_seconds,
                'youtube_url': youtube_url
            }
            for key, val in kwargs.items():
                if val is not None:
                    updates.append(f"{key} = ?")
                    params.append(val)
            if updates:
                params.append(item_id)
                conn.execute(
                    f"UPDATE media_items SET {', '.join(updates)} WHERE id = ?",
                    tuple(params)
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

def clear_rankings_for_country_and_week(db_path: str, country_code: str, week: str, conn: sqlite3.Connection | None = None):
    """Deletes rankings specifically for the given country_code and week."""
    if conn is not None:
        conn.execute("DELETE FROM rankings WHERE country_code = ? AND week = ?", (country_code.upper(), week))
    else:
        connection = _get_connection(db_path)
        try:
            with connection:
                connection.execute("DELETE FROM rankings WHERE country_code = ? AND week = ?", (country_code.upper(), week))
        finally:
            connection.close()


def insert_ranking(
    db_path: str,
    country_code: str,
    category: str,
    rank: int,
    week: str,
    media_item_id: int,
    country_name: str | None = None,
    weekly_hours_viewed: int | None = None,
    weekly_views: int | None = None,
    cumulative_weeks_in_top_10: int | None = None
):
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO rankings (
                    country_code, country_name, category, rank, week, media_item_id,
                    weekly_hours_viewed, weekly_views, cumulative_weeks_in_top_10
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    country_code, country_name, category, rank, week, media_item_id,
                    weekly_hours_viewed, weekly_views, cumulative_weeks_in_top_10
                )
            )
    finally:
        conn.close()

def get_active_rankings(db_path: str, country_code: str, category: str, week: str) -> list[dict]:
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT 
                r.id AS ranking_id, r.country_code, r.country_name, r.category, r.rank, r.week,
                r.weekly_hours_viewed, r.weekly_views, r.cumulative_weeks_in_top_10,
                m.id AS media_item_id, m.title, m.local_title, m.show_title, m.season_title,
                m.type, m.release_year, m.season_name, m.folder_name, m.file_path, m.poster_url,
                m.logo_url, m.video_url, m.subtitle_url, m.youtube_url, m.netflix_id, m.synopsis, m.maturity_rating,
                m.runtime_seconds, m.status, m.added_at, m.last_seen_at
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

def get_media_item_by_netflix_id(db_path: str, netflix_id_or_id: int | str, item_type: str | None = None) -> dict | None:
    conn = _get_connection(db_path)
    try:
        val_str = str(netflix_id_or_id)
        val_int = int(netflix_id_or_id) if val_str.isdigit() else -1
        
        if item_type:
            cursor = conn.execute("""
                SELECT * FROM media_items
                WHERE (netflix_id = ? OR netflix_id = ? OR id = ?) AND type = ?
                LIMIT 1
            """, (val_int, val_str, val_int, item_type.lower()))
            row = cursor.fetchone()
            if row:
                return dict(row)
        
        cursor = conn.execute("""
            SELECT * FROM media_items
            WHERE netflix_id = ? OR netflix_id = ? OR id = ?
            LIMIT 1
        """, (val_int, val_str, val_int))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_prev_next_media_items(db_path: str, current_item: dict) -> tuple[dict | None, dict | None]:
    """Gets the previous and next media items of the same format/type for navigation."""
    if not current_item:
        return None, None

    conn = _get_connection(db_path)
    try:
        item_type = str(current_item.get("type", "movie")).lower()
        current_id = current_item.get("id")

        # Get latest week if rankings exist
        latest_week = ""
        cursor = conn.execute("SELECT week FROM rankings ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            latest_week = row["week"]

        if latest_week:
            cursor = conn.execute("""
                SELECT m.*
                FROM media_items m
                LEFT JOIN (
                    SELECT media_item_id, MIN(rank) as min_rank
                    FROM rankings
                    WHERE week = ?
                    GROUP BY media_item_id
                ) r ON m.id = r.media_item_id
                WHERE m.type = ?
                ORDER BY 
                    CASE WHEN r.min_rank IS NOT NULL THEN 0 ELSE 1 END,
                    r.min_rank ASC,
                    m.id ASC
            """, (latest_week, item_type))
        else:
            cursor = conn.execute("""
                SELECT * FROM media_items
                WHERE type = ?
                ORDER BY id ASC
            """, (item_type,))

        items = [dict(r) for r in cursor.fetchall()]
        if not items or len(items) <= 1:
            return None, None

        current_index = -1
        for idx, itm in enumerate(items):
            if itm["id"] == current_id or (itm.get("netflix_id") and current_item.get("netflix_id") and itm.get("netflix_id") == current_item.get("netflix_id")):
                current_index = idx
                break

        if current_index == -1:
            return None, None

        prev_index = (current_index - 1) % len(items)
        next_index = (current_index + 1) % len(items)

        return items[prev_index], items[next_index]
    finally:
        conn.close()


def calculate_expected_total_tasks(db_path: str) -> int:
    """Calculates total expected content items to crawl based on monitored countries and types (10 items per format)."""
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("SELECT country_code, formats FROM monitored_countries")
        countries = [dict(row) for row in cursor.fetchall()]
        
        cursor = conn.execute("SELECT COUNT(*) as count FROM media_items WHERE status = 'pending'")
        pending_count = cursor.fetchone()['count']
    finally:
        conn.close()
        
    expected_count = 0
    for c in countries:
        fmt = (c.get("formats") or "movie,tv").lower()
        if "movie" in fmt or "film" in fmt:
            expected_count += 10
        if "tv" in fmt:
            expected_count += 10
            
    return max(expected_count, pending_count)


def reset_stubs_and_failed_media_items(db_path: str) -> list[int]:
    """
    Checks all media items in the database for zero-byte local video files OR status = 'failed'.
    Resets their status to 'pending' so full video content can be searched and downloaded.
    Returns a list of updated media item IDs.
    """
    conn = _get_connection(db_path)
    reset_ids = []
    try:
        cursor = conn.execute("SELECT id, file_path, status FROM media_items")
        rows = cursor.fetchall()
        for row in rows:
            fpath = row["file_path"]
            status = row["status"]
            is_zero_byte = fpath and os.path.exists(fpath) and os.path.getsize(fpath) == 0
            is_failed = (status == "failed")
            if is_zero_byte or is_failed:
                conn.execute("UPDATE media_items SET status = 'pending' WHERE id = ?", (row["id"],))
                reset_ids.append(row["id"])
        conn.commit()
    finally:
        conn.close()
    return reset_ids


def reset_zero_byte_media_stubs(db_path: str) -> list[int]:
    return reset_stubs_and_failed_media_items(db_path)


