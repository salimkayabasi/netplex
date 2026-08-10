import os
import csv
import re
import datetime
import urllib.request
from src.database import (
    get_monitored_countries,
    upsert_media_item,
    insert_ranking,
    clear_rankings_for_week
)

def fetch_top10_tsv(url: str, cache_path: str) -> str:
    """Stream-downloads the TSV dataset and caches it locally to avoid redundant downloads."""
    # Ensure directory exists
    cache_dir = os.path.dirname(os.path.abspath(cache_path))
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return cache_path
        
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    with urllib.request.urlopen(req) as response, open(cache_path, 'wb') as out_file:
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            out_file.write(chunk)
            
    return cache_path

def get_latest_available_week(tsv_path: str) -> str:
    """Reads the TSV rows and determines the most recent week date string."""
    latest_week = ""
    with open(tsv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            week = row.get('week')
            if week and week > latest_week:
                latest_week = week
    return latest_week

def parse_title_and_year(title_str: str) -> tuple[str, int]:
    """Extracts a 4-digit release year in parentheses from title if present. Otherwise, defaults to current year."""
    match = re.search(r'\s*\((\d{4})\)\s*$', title_str)
    if match:
        year = int(match.group(1))
        clean_title = title_str[:match.start()].strip()
        return clean_title, year
    return title_str.strip(), datetime.datetime.now().year

def parse_top10_data(tsv_path: str, countries_config: list[dict], target_week: str) -> list[dict]:
    """Parses a TSV dataset, filtering by targets and formats, returning standardized metadata records."""
    parsed_results = []
    
    # Map configurations by country_code (case-insensitive) for fast lookup
    config_map = {c['country_code'].upper(): c['formats'] for c in countries_config}
    
    with open(tsv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        headers = reader.fieldnames or []
        is_country_tsv = "country_iso2" in headers
        
        for row in reader:
            row_week = row.get('week')
            if row_week != target_week:
                continue
                
            # Filter by country code and formats config
            if is_country_tsv:
                country_iso = row.get('country_iso2', '').upper()
                if country_iso not in config_map:
                    continue
                country_code = country_iso
                formats_allowed = config_map[country_iso]
            else:
                if 'GLOBAL' not in config_map:
                    continue
                country_code = 'GLOBAL'
                formats_allowed = config_map['GLOBAL']
                
            # Category Mapping
            raw_category = row.get('category', '')
            if raw_category.startswith('Films'):
                category = 'Films'
                item_type = 'movie'
            elif raw_category.startswith('TV'):
                category = 'TV'
                item_type = 'tv'
            else:
                continue
                
            # Format filtering
            if formats_allowed == 'movies' and item_type != 'movie':
                continue
            if formats_allowed == 'tv' and item_type != 'tv':
                continue
                
            # Show and Season parsing
            show_title = row.get('show_title', '').strip()
            season_title = row.get('season_title', '').strip()
            
            if season_title and season_title != 'N/A':
                show_title_clean = show_title.strip()
                season_title_clean = season_title.strip()
                if season_title_clean.lower().startswith(show_title_clean.lower()):
                    season_name = season_title_clean[len(show_title_clean):].lstrip(':').strip()
                    title = show_title_clean
                else:
                    if ':' in season_title_clean:
                        parts = season_title_clean.split(':', 1)
                        title = parts[0].strip()
                        season_name = parts[1].strip()
                    else:
                        title = show_title_clean
                        season_name = season_title_clean
            else:
                title = show_title.strip()
                season_name = None
                
            # Extract year if present
            title, year = parse_title_and_year(title)
            
            # Format folder name
            folder_name = f"{title} ({year})"
            
            # Rank
            try:
                rank = int(row.get('weekly_rank', '0'))
            except ValueError:
                continue
                
            parsed_results.append({
                'country_code': country_code,
                'category': category,
                'rank': rank,
                'title': title,
                'type': item_type,
                'release_year': year,
                'season_name': season_name,
                'folder_name': folder_name
            })
            
    return parsed_results

def crawl_netflix_top10(db_path: str):
    """Crawl, parse, and synchronize NetPlex rankings with Netflix Top 10 portal."""
    countries_config = get_monitored_countries(db_path)
    if not countries_config:
        return
        
    # Resolve cache directory relative to database path
    if db_path == ":memory:":
        cache_dir = "cache"
    else:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'cache')
        
    os.makedirs(cache_dir, exist_ok=True)
    
    global_config = [c for c in countries_config if c['country_code'].upper() == 'GLOBAL']
    country_configs = [c for c in countries_config if c['country_code'].upper() != 'GLOBAL']
    
    cleared_weeks = set()
    
    # Process Global rankings
    if global_config:
        global_url = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"
        global_path = os.path.join(cache_dir, "all-weeks-global.tsv")
        fetch_top10_tsv(global_url, global_path)
        
        latest_week = get_latest_available_week(global_path)
        if latest_week:
            parsed_data = parse_top10_data(global_path, global_config, latest_week)
            
            if latest_week not in cleared_weeks:
                clear_rankings_for_week(db_path, latest_week)
                cleared_weeks.add(latest_week)
                
            for item in parsed_data:
                media_item_id = upsert_media_item(
                    db_path,
                    title=item['title'],
                    type=item['type'],
                    release_year=item['release_year'],
                    season_name=item['season_name'],
                    folder_name=item['folder_name']
                )
                insert_ranking(
                    db_path,
                    country_code=item['country_code'],
                    category=item['category'],
                    rank=item['rank'],
                    week=latest_week,
                    media_item_id=media_item_id
                )
                
    # Process Country rankings
    if country_configs:
        countries_url = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
        countries_path = os.path.join(cache_dir, "all-weeks-countries.tsv")
        fetch_top10_tsv(countries_url, countries_path)
        
        latest_week = get_latest_available_week(countries_path)
        if latest_week:
            parsed_data = parse_top10_data(countries_path, country_configs, latest_week)
            
            if latest_week not in cleared_weeks:
                clear_rankings_for_week(db_path, latest_week)
                cleared_weeks.add(latest_week)
                
            for item in parsed_data:
                media_item_id = upsert_media_item(
                    db_path,
                    title=item['title'],
                    type=item['type'],
                    release_year=item['release_year'],
                    season_name=item['season_name'],
                    folder_name=item['folder_name']
                )
                insert_ranking(
                    db_path,
                    country_code=item['country_code'],
                    category=item['category'],
                    rank=item['rank'],
                    week=latest_week,
                    media_item_id=media_item_id
                )
