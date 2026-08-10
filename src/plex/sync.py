import logging
import re
from typing import Any
from rapidfuzz import fuzz

try:
    from plexapi.server import PlexServer
    from plexapi.exceptions import PlexApiException
except ImportError:
    PlexServer = Any
    PlexApiException = Exception

from src.database import (
    get_setting,
    get_monitored_countries,
    get_active_rankings
)

logger = logging.getLogger(__name__)


def connect_to_plex(url: str, token: str, timeout: int = 10) -> PlexServer:
    """Initializes and returns a PlexServer instance with specified timeout."""
    return PlexServer(url, token, timeout=timeout)


def match_library_item(
    plex_library,
    title: str,
    year: int | str | None = None,
    threshold: float = 85.0
):
    """Searches a Plex library section for the closest title match using rapidfuzz.
    
    If year is provided, matches with year discrepancy > 1 are excluded.
    Returns the matched Plex item object or None if match score is below threshold.
    """
    if not plex_library:
        return None
        
    best_item = None
    best_score = 0.0
    
    # Fetch candidates from the library section
    try:
        candidates = plex_library.all()
    except Exception as e:
        logger.warning(f"Error fetching candidates from library section: {e}")
        return None

    target_title = title.strip().lower()
    search_year = int(year) if year is not None else None

    for item in candidates:
        candidate_title = getattr(item, "title", "")
        if not candidate_title:
            continue
            
        # Strip trailing years in parens e.g., "Inside Out 2 (2024)" -> "Inside Out 2"
        clean_candidate = re.sub(r'\s*[\(\[\{]\d{4}[\)\]\}]\s*', '', candidate_title).strip().lower()
        candidate_title_lower = candidate_title.strip().lower()
        
        # Check year constraint if specified
        if search_year is not None:
            item_year = getattr(item, "year", None)
            if item_year is not None:
                try:
                    if abs(int(item_year) - search_year) > 1:
                        continue
                except (ValueError, TypeError):
                    pass

        # Calculate similarity scores
        score_ratio = fuzz.ratio(target_title, clean_candidate)
        score_token = fuzz.token_sort_ratio(target_title, clean_candidate)
        score_wratio = fuzz.WRatio(target_title, candidate_title_lower)
        score = max(score_ratio, score_token, score_wratio)

        if score >= threshold and score > best_score:
            best_score = score
            best_item = item

    return best_item



def _get_target_library_section(plex_server, media_type: str | None = None, library_name: str | None = None):
    """Helper to locate appropriate library section on Plex server."""
    if library_name:
        try:
            return plex_server.library.section(library_name)
        except Exception:
            pass

    sections = plex_server.library.sections()
    if not sections:
        return None

    if media_type:
        target_type = "movie" if media_type.lower() in ("movie", "films", "movies") else "show"
        for sec in sections:
            if getattr(sec, "type", None) == target_type:
                return sec

    return sections[0]


def sync_plex_collection(
    plex_server,
    collection_name: str,
    ranked_items: list[dict],
    library_name: str | None = None,
    threshold: float = 85.0
):
    """Synchronizes a Plex Collection with ranked items.
    
    Adds matched items in rank order, removes items no longer in top 10,
    and configures collection mode.
    """
    if not ranked_items:
        return None

    # Determine media type from ranked items
    first_item_type = ranked_items[0].get("type") or ranked_items[0].get("category")
    section = _get_target_library_section(plex_server, media_type=first_item_type, library_name=library_name)
    if not section:
        logger.warning("No suitable Plex library section found for collection sync.")
        return None

    # Match items in rank order
    matched_items = []
    for item_data in ranked_items:
        title = item_data.get("title")
        year = item_data.get("release_year")
        if title:
            matched = match_library_item(section, title=title, year=year, threshold=threshold)
            if matched and matched not in matched_items:
                matched_items.append(matched)

    # Search for existing collection
    existing_collection = None
    try:
        collections = section.collections(title=collection_name)
        if collections:
            existing_collection = collections[0]
    except Exception:
        pass

    if existing_collection:
        # Remove items no longer in ranking
        try:
            current_items = existing_collection.items()
            items_to_remove = [item for item in current_items if item not in matched_items]
            if items_to_remove:
                existing_collection.removeItems(items_to_remove)
            
            # Add missing items
            items_to_add = [item for item in matched_items if item not in current_items]
            if items_to_add:
                existing_collection.addItems(items_to_add)
        except Exception as e:
            logger.warning(f"Error updating collection items: {e}")
        return existing_collection
    else:
        if matched_items:
            try:
                collection = section.createCollection(title=collection_name, items=matched_items)
                return collection
            except Exception as e:
                logger.error(f"Failed to create collection '{collection_name}': {e}")
                return None
        return None


def sync_plex_playlist(
    plex_server,
    playlist_name: str,
    ranked_items: list[dict],
    threshold: float = 85.0
):
    """Fallback: Rebuilds a Plex Playlist containing matched items in order."""
    if not ranked_items:
        return None

    # Match items across sections
    matched_items = []
    sections = plex_server.library.sections()
    
    for item_data in ranked_items:
        title = item_data.get("title")
        year = item_data.get("release_year")
        media_type = item_data.get("type") or item_data.get("category")
        if not title:
            continue
            
        target_section = _get_target_library_section(plex_server, media_type=media_type)
        if target_section:
            matched = match_library_item(target_section, title=title, year=year, threshold=threshold)
            if matched and matched not in matched_items:
                matched_items.append(matched)

    if not matched_items:
        return None

    # Check existing playlist and delete
    try:
        existing_playlists = plex_server.playlists(title=playlist_name)
        for pl in existing_playlists:
            pl.delete()
    except Exception:
        pass

    # Create playlist
    try:
        playlist = plex_server.createPlaylist(playlist_name, items=matched_items)
        return playlist
    except Exception as e:
        logger.error(f"Failed to create playlist '{playlist_name}': {e}")
        return None


def run_plex_sync(db_path: str, week: str) -> bool:
    """Offline resilience hook: Top-level entrypoint for Phase 2 synchronization.
    
    Reads Plex credentials and active rankings from database and syncs collections.
    Wraps entire sync execution in try-except block to gracefully catch timeouts,
    connection failures, or auth errors without crashing the main process.
    """
    plex_url = get_setting(db_path, "plex_url")
    plex_token = get_setting(db_path, "plex_token")

    if not plex_url or not plex_token:
        logger.warning("Plex URL or Token missing in settings database. Skipping Plex Sync.")
        return False

    try:
        plex_server = connect_to_plex(plex_url, plex_token, timeout=10)
        monitored = get_monitored_countries(db_path)
        
        for record in monitored:
            country_code = record.get("country_code")
            formats_setting = record.get("formats", "both")
            
            categories = []
            if formats_setting in ("movies", "both"):
                categories.append("Films")
            if formats_setting in ("tv", "both"):
                categories.append("TV")
                
            for category in categories:
                rankings = get_active_rankings(db_path, country_code, category, week)
                if rankings:
                    collection_name = f"Netflix Top 10 - {country_code} {category}"
                    sync_plex_collection(plex_server, collection_name, rankings)
                    
        return True
    except Exception as e:
        logger.error(f"Plex sync operation failed (offline or auth error): {e}")
        return False
