import os
import sqlite3
import pytest
from src.database import (
    init_db,
    get_setting,
    set_setting,
    get_monitored_countries,
    set_monitored_country,
    remove_monitored_country,
    upsert_media_item,
    update_media_item_status,
    clear_rankings_for_week,
    insert_ranking,
    get_active_rankings,
    get_orphaned_media_items,
    _get_connection
)

@pytest.fixture
def db_path(tmp_path):
    db_file = tmp_path / "netplex.db"
    return str(db_file)

@pytest.fixture
def initialized_db(db_path):
    init_db(db_path)
    return db_path

def test_init_db_creates_tables_and_seeds(initialized_db):
    conn = _get_connection(initialized_db)
    try:
        # Verify tables exist
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row['name'] for row in cursor.fetchall()]
        assert "settings" in tables
        assert "monitored_countries" in tables
        assert "media_items" in tables
        assert "rankings" in tables

        # Verify seeded settings
        assert get_setting(initialized_db, "update_interval_hours") == "168"
        assert get_setting(initialized_db, "log_level") == "INFO"
        assert get_setting(initialized_db, "trailer_subtitles") == "false"
        assert get_setting(initialized_db, "subtitle_languages") == "en"
        
        client_id = get_setting(initialized_db, "plex_client_id")
        assert client_id is not None
        assert len(client_id) > 10
    finally:
        conn.close()

def test_settings_crud(initialized_db):
    # Get non-existent setting with and without default
    assert get_setting(initialized_db, "non_existent") is None
    assert get_setting(initialized_db, "non_existent", default="fallback") == "fallback"

    # Set and get setting
    set_setting(initialized_db, "custom_key", "custom_value")
    assert get_setting(initialized_db, "custom_key") == "custom_value"

    # Update setting
    set_setting(initialized_db, "custom_key", "updated_value")
    assert get_setting(initialized_db, "custom_key") == "updated_value"

def test_monitored_countries_crud(initialized_db):
    # Initially empty
    countries = get_monitored_countries(initialized_db)
    assert len(countries) == 0

    # Add countries
    set_monitored_country(initialized_db, "US", "both")
    set_monitored_country(initialized_db, "TR", "movies")
    
    countries = get_monitored_countries(initialized_db)
    assert len(countries) == 2
    
    # Verify formats
    us_config = next(c for c in countries if c['country_code'] == "US")
    tr_config = next(c for c in countries if c['country_code'] == "TR")
    assert us_config['formats'] == "both"
    assert tr_config['formats'] == "movies"

    # Update format
    set_monitored_country(initialized_db, "TR", "tv")
    countries = get_monitored_countries(initialized_db)
    tr_config = next(c for c in countries if c['country_code'] == "TR")
    assert tr_config['formats'] == "tv"

    # Remove country
    remove_monitored_country(initialized_db, "US")
    countries = get_monitored_countries(initialized_db)
    assert len(countries) == 1
    assert countries[0]['country_code'] == "TR"

def test_upsert_media_item(initialized_db):
    # Insert new item
    item_id = upsert_media_item(
        initialized_db,
        title="Inside Out 2",
        type="movie",
        release_year=2024,
        season_name=None,
        folder_name="Inside Out 2 (2024)"
    )
    assert item_id > 0

    # Retrieve and verify details
    conn = _get_connection(initialized_db)
    try:
        row = conn.execute("SELECT * FROM media_items WHERE id = ?", (item_id,)).fetchone()
        assert row['title'] == "Inside Out 2"
        assert row['type'] == "movie"
        assert row['release_year'] == 2024
        assert row['season_name'] is None
        assert row['folder_name'] == "Inside Out 2 (2024)"
        assert row['status'] == "pending"
        assert row['added_at'] is not None
        assert row['last_seen_at'] is not None
        added_at = row['added_at']
    finally:
        conn.close()

    # Upsert duplicate, should return same ID and update folder_name/last_seen_at
    dup_id = upsert_media_item(
        initialized_db,
        title="Inside Out 2",
        type="movie",
        release_year=2024,
        season_name=None,
        folder_name="Inside Out 2 (2024) Updated"
    )
    assert dup_id == item_id

    conn = _get_connection(initialized_db)
    try:
        row = conn.execute("SELECT * FROM media_items WHERE id = ?", (item_id,)).fetchone()
        assert row['folder_name'] == "Inside Out 2 (2024) Updated"
        # Since it's done quickly, added_at and last_seen_at might be equal, but added_at should remain unchanged
        assert row['added_at'] == added_at
    finally:
        conn.close()

    # Insert TV Show with season
    tv_id = upsert_media_item(
        initialized_db,
        title="Stranger Things",
        type="tv",
        release_year=2016,
        season_name="Season 4",
        folder_name="Stranger Things (2016)"
    )
    assert tv_id != item_id

def test_media_item_constraints(initialized_db):
    conn = _get_connection(initialized_db)
    try:
        # Invalid type check constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO media_items (title, type, release_year, folder_name, status) VALUES (?, ?, ?, ?, ?)",
                ("Bad Type", "invalid_type", 2024, "Bad Type (2024)", "pending")
            )
            
        # Invalid status check constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO media_items (title, type, release_year, folder_name, status) VALUES (?, ?, ?, ?, ?)",
                ("Bad Status", "movie", 2024, "Bad Status (2024)", "invalid_status")
            )
    finally:
        conn.close()

def test_update_media_item_status(initialized_db):
    item_id = upsert_media_item(
        initialized_db,
        title="Inside Out 2",
        type="movie",
        release_year=2024,
        season_name=None,
        folder_name="Inside Out 2 (2024)"
    )

    # Update status only
    update_media_item_status(initialized_db, item_id, "downloaded")
    conn = _get_connection(initialized_db)
    try:
        row = conn.execute("SELECT status, file_path FROM media_items WHERE id = ?", (item_id,)).fetchone()
        assert row['status'] == "downloaded"
        assert row['file_path'] is None
    finally:
        conn.close()

    # Update status and file_path
    update_media_item_status(initialized_db, item_id, "downloaded", file_path="/data/movies/Inside Out 2 (2024)/Inside Out 2 (2024).mp4")
    conn = _get_connection(initialized_db)
    try:
        row = conn.execute("SELECT status, file_path FROM media_items WHERE id = ?", (item_id,)).fetchone()
        assert row['status'] == "downloaded"
        assert row['file_path'] == "/data/movies/Inside Out 2 (2024)/Inside Out 2 (2024).mp4"
    finally:
        conn.close()

def test_rankings_api_and_constraints(initialized_db):
    item_id_1 = upsert_media_item(initialized_db, "Movie 1", "movie", 2024, None, "Movie 1 (2024)")
    item_id_2 = upsert_media_item(initialized_db, "Movie 2", "movie", 2024, None, "Movie 2 (2024)")

    # Insert rankings
    insert_ranking(initialized_db, "US", "Movies", 1, "2026-08-09", item_id_1)
    insert_ranking(initialized_db, "US", "Movies", 2, "2026-08-09", item_id_2)

    # Verify foreign key constraint (non-existent media_item_id)
    with pytest.raises(sqlite3.IntegrityError):
        insert_ranking(initialized_db, "US", "Movies", 3, "2026-08-09", 99999)

    # Verify rank check constraint (rank < 1)
    with pytest.raises(sqlite3.IntegrityError):
        insert_ranking(initialized_db, "US", "Movies", 0, "2026-08-09", item_id_1)

    # Verify rank check constraint (rank > 10)
    with pytest.raises(sqlite3.IntegrityError):
        insert_ranking(initialized_db, "US", "Movies", 11, "2026-08-09", item_id_1)

    # Verify category check constraint
    with pytest.raises(sqlite3.IntegrityError):
        insert_ranking(initialized_db, "US", "Invalid Category", 3, "2026-08-09", item_id_1)

    # Retrieve active rankings and check sorting/joins
    rankings = get_active_rankings(initialized_db, "US", "Movies", "2026-08-09")
    assert len(rankings) == 2
    assert rankings[0]['rank'] == 1
    assert rankings[0]['title'] == "Movie 1"
    assert rankings[1]['rank'] == 2
    assert rankings[1]['title'] == "Movie 2"

    # Clear rankings for the week
    clear_rankings_for_week(initialized_db, "2026-08-09")
    rankings = get_active_rankings(initialized_db, "US", "Movies", "2026-08-09")
    assert len(rankings) == 0

def test_orphan_lookup(initialized_db):
    item_id_1 = upsert_media_item(initialized_db, "Movie 1", "movie", 2024, None, "Movie 1 (2024)")
    item_id_2 = upsert_media_item(initialized_db, "Movie 2", "movie", 2024, None, "Movie 2 (2024)")
    item_id_3 = upsert_media_item(initialized_db, "Movie 3", "movie", 2024, None, "Movie 3 (2024)")

    # Rankings for week 1
    insert_ranking(initialized_db, "US", "Movies", 1, "2026-08-02", item_id_1)
    insert_ranking(initialized_db, "US", "Movies", 2, "2026-08-02", item_id_2)
    insert_ranking(initialized_db, "US", "Movies", 3, "2026-08-02", item_id_3)

    # Rankings for week 2: only Movie 1 and Movie 2 are present
    insert_ranking(initialized_db, "US", "Movies", 1, "2026-08-09", item_id_1)
    insert_ranking(initialized_db, "US", "Movies", 2, "2026-08-09", item_id_2)

    # For week 2026-08-09, Movie 3 has no rankings and is therefore orphaned
    orphans = get_orphaned_media_items(initialized_db, "2026-08-09")
    assert len(orphans) == 1
    assert orphans[0]['id'] == item_id_3
    assert orphans[0]['title'] == "Movie 3"

def test_init_db_creates_parent_directories_if_not_exist(tmp_path):
    db_file = tmp_path / "new_subdir" / "netplex.db"
    assert not db_file.parent.exists()
    
    # This should automatically create the subdirectory and initialize db
    init_db(str(db_file))
    assert db_file.exists()
    
    # Confirm it's a valid SQLite database
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert "settings" in tables
    finally:
        conn.close()

def test_tudum_metadata_fields(initialized_db):
    item_id = upsert_media_item(
        initialized_db,
        title="72 HOURS",
        type="movie",
        release_year=2026,
        season_name=None,
        folder_name="72 HOURS (2026)",
        local_title="72 Saat",
        netflix_id=82742346,
        show_title="72 HOURS",
        season_title=None,
        synopsis="After their divorce...",
        maturity_rating="16+",
        runtime_seconds=6300,
        logo_url="https://img.nflx.net/logo.png",
        video_url="https://video.nflx.net/trailer.mp4",
        subtitle_url="https://sub.nflx.net/sub.vtt",
        poster_url="https://img.nflx.net/poster.jpg"
    )
    assert item_id > 0

    insert_ranking(
        initialized_db,
        country_code="TR",
        category="Movies",
        rank=1,
        week="2026-08-02",
        media_item_id=item_id,
        country_name="Turkey",
        weekly_hours_viewed=28400000,
        weekly_views=14200000,
        cumulative_weeks_in_top_10=3
    )

    rankings = get_active_rankings(initialized_db, "TR", "Movies", "2026-08-02")
    assert len(rankings) == 1
    r = rankings[0]
    assert r['title'] == "72 HOURS"
    assert r['local_title'] == "72 Saat"
    assert r['netflix_id'] == 82742346
    assert r['synopsis'] == "After their divorce..."
    assert r['maturity_rating'] == "16+"
    assert r['runtime_seconds'] == 6300
    assert r['logo_url'] == "https://img.nflx.net/logo.png"
    assert r['country_name'] == "Turkey"
    assert r['weekly_hours_viewed'] == 28400000
    assert r['weekly_views'] == 14200000
    assert r['cumulative_weeks_in_top_10'] == 3

def test_calculate_expected_total_tasks(initialized_db):
    from src.database import set_monitored_country, calculate_expected_total_tasks
    set_monitored_country(initialized_db, "US", "movie,tv")
    set_monitored_country(initialized_db, "TR", "movie,tv")
    
    # 2 countries * 2 types (movies, tv) * 10 items = 40 contents total
    total = calculate_expected_total_tasks(initialized_db)
    assert total == 40


