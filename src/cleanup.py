import os
import shutil
import logging
import re
from src.database import _get_connection, get_orphaned_media_items

logger = logging.getLogger(__name__)

def find_orphaned_media(db_path: str, latest_week: str) -> list[dict]:
    """
    Queries the database to return all media_items that do not appear in
    the rankings table for latest_week.
    """
    return get_orphaned_media_items(db_path, latest_week)

def is_netplex_file(filename: str, folder_name: str) -> bool:
    """
    Determines if a file in a media folder was created by NetPlex.
    Allowed NetPlex files:
      - Metadata: movie.nfo, tvshow.nfo (or any *.nfo file)
      - Movie assets matching folder_name prefix: <folder_name>.*.mp4/mkv/webm/srt/vtt
      - TV assets matching episode trailer pattern: SXXE00 - Trailer.*.mp4/mkv/webm/srt/vtt
    """
    name_lower = filename.lower()
    
    # Standard NFO metadata files
    if name_lower in ("movie.nfo", "tvshow.nfo") or name_lower.endswith(".nfo"):
        return True
        
    # Check if file matches folder_name prefix (Movie layout)
    # e.g. "The Irishman (2019).mp4", "The Irishman (2019).en.srt"
    folder_prefix = folder_name.lower()
    if name_lower.startswith(folder_prefix):
        ext = os.path.splitext(name_lower)[1]
        if ext in (".mp4", ".mkv", ".webm", ".srt", ".vtt"):
            return True

    # Check TV episode trailer layout: SXXE00 - Trailer...
    # e.g., "s01e00 - trailer.mp4", "s01e00 - trailer.en.srt"
    if re.match(r'^s\d{2}e00\s*-\s*trailer.*', name_lower):
        ext = os.path.splitext(name_lower)[1]
        if ext in (".mp4", ".mkv", ".webm", ".srt", ".vtt"):
            return True

    return False

def delete_media_folder(folder_path: str, base_data_dir: str = "/data") -> bool:
    """
    Validates that folder_path is safely inside base_data_dir/movies or base_data_dir/tv,
    checks that all files were created by NetPlex, and deletes the folder if safe.
    If unrelated files are present or path is outside allowed dirs, logs error and skips deletion.
    """
    abs_folder = os.path.abspath(folder_path)
    abs_movies_dir = os.path.abspath(os.path.join(base_data_dir, "movies"))
    abs_tv_dir = os.path.abspath(os.path.join(base_data_dir, "tv"))

    # Directory traversal safety check: folder_path must be strictly inside movies or tv folder
    is_in_movies = os.path.commonpath([abs_folder, abs_movies_dir]) == abs_movies_dir and abs_folder != abs_movies_dir
    is_in_tv = os.path.commonpath([abs_folder, abs_tv_dir]) == abs_tv_dir and abs_folder != abs_tv_dir

    if not (is_in_movies or is_in_tv):
        logger.error(f"Security error: '{folder_path}' is not inside allowed media directories ({abs_movies_dir} or {abs_tv_dir}). Deletion aborted.")
        return False

    if not os.path.exists(abs_folder):
        logger.info(f"Folder '{folder_path}' does not exist on disk. Skipping file deletion.")
        return True

    folder_name = os.path.basename(abs_folder)
    
    # Scan all files recursively inside abs_folder
    unrelated_files = []
    
    for root, _, files in os.walk(abs_folder):
        for f in files:
            full_file_path = os.path.join(root, f)
            if not is_netplex_file(f, folder_name):
                unrelated_files.append(os.path.relpath(full_file_path, abs_folder))

    if unrelated_files:
        logger.error(f"Unrelated file(s) found in '{folder_path}': {unrelated_files}. Skipping folder deletion.")
        return False

    # Safe to delete folder and contents
    try:
        shutil.rmtree(abs_folder)
        logger.info(f"Successfully deleted media folder: '{folder_path}'")
        return True
    except Exception as e:
        logger.error(f"Failed to delete media folder '{folder_path}': {e}")
        return False

def prune_orphaned_records(db_path: str, orphan_ids: list[int]) -> int:
    """
    Removes ranking records and deletes media item rows for orphan_ids from the database.
    """
    if not orphan_ids:
        return 0
    conn = _get_connection(db_path)
    try:
        with conn:
            placeholders = ",".join("?" for _ in orphan_ids)
            conn.execute(f"DELETE FROM rankings WHERE media_item_id IN ({placeholders})", orphan_ids)
            cursor = conn.execute(f"DELETE FROM media_items WHERE id IN ({placeholders})", orphan_ids)
            return cursor.rowcount
    finally:
        conn.close()

def run_cleanup_cycle(db_path: str, latest_week: str, media_dir: str = "/data") -> dict:
    """
    Executes a full cleanup cycle:
    1. Finds orphaned media items for latest_week.
    2. Deletes their media folders if safe.
    3. Prunes database records for items whose folders were successfully deleted (or missing).
    """
    orphans = find_orphaned_media(db_path, latest_week)
    deleted_folders = 0
    pruned_ids = []

    for orphan in orphans:
        item_type = orphan.get("type", "movie")
        sub_dir = "movies" if item_type == "movie" else "tv"
        folder_path = os.path.join(media_dir, sub_dir, orphan["folder_name"])
        
        success = delete_media_folder(folder_path, base_data_dir=media_dir)
        if success:
            deleted_folders += 1
            pruned_ids.append(orphan["id"])

    records_pruned = prune_orphaned_records(db_path, pruned_ids)
    
    return {
        "orphans_found": len(orphans),
        "folders_deleted": deleted_folders,
        "records_pruned": records_pruned
    }
