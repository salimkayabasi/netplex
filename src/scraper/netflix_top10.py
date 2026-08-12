import os
import csv
import re
import datetime
import urllib.request
from src.database import (
    get_monitored_countries,
    upsert_media_item,
    insert_ranking,
    clear_rankings_for_week,
    clear_rankings_for_country_and_week,
    update_media_item_poster
)
from src.crawler_lock import set_crawl_progress
import http.client
import json

COUNTRY_SLUGS = {
    'GLOBAL': '', 'US': 'united-states', 'GB': 'united-kingdom',
    'CA': 'canada', 'AU': 'australia', 'DE': 'germany',
    'FR': 'france', 'ES': 'spain', 'IT': 'italy',
    'JP': 'japan', 'KR': 'south-korea', 'BR': 'brazil',
    'MX': 'mexico', 'IN': 'india', 'TR': 'turkey'
}

def fetch_country_top10_metadata(country_code: str) -> dict:
    slug = COUNTRY_SLUGS.get(country_code.upper(), '')
    url = f"https://www.netflix.com/tudum/top10/{slug}".rstrip('/')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('utf-8')
    except http.client.IncompleteRead as e:
        html = e.partial.decode('utf-8', errors='ignore')
    except Exception:
        return {}

    match = re.search(r"netflix\.reactContext\.models\.graphql\s*=\s*JSON\.parse\('(.*?)'\)", html)
    if not match:
        return {}
        
    try:
        data = json.loads(match.group(1).encode('utf-8').decode('unicode_escape'))
    except Exception:
        return {}

    mapping = {}
    for k, v in data.get('data', {}).items():
        if 'PulseTop10ItemEntity' in k and v.get('top10Video'):
            top_vid_obj = v['top10Video']
            vid = top_vid_obj.get('videoId')
            title = top_vid_obj.get('title')
            if not title:
                continue
            show_title = v.get('showTitle') or top_vid_obj.get('showTitle')
            season_title = v.get('seasonTitle') or top_vid_obj.get('seasonTitle')
            release_year = v.get('releaseYear') or top_vid_obj.get('releaseYear')
            synopsis = v.get('shortSynopsis') or v.get('synopsis') or top_vid_obj.get('synopsis')
            maturity_rating = v.get('maturityRating') or top_vid_obj.get('maturityRating')
            runtime_seconds = v.get('runtimeSeconds') or top_vid_obj.get('runtimeSeconds')

            art = v.get('artwork', {})
            poster = None
            for art_key in ['storyArt', 'sdpArt']:
                if art.get(art_key):
                    urls_sized = (art[art_key].get('urlsSized({\"sizes\":{\"height\":675,\"width\":1200}})') or
                                  art[art_key].get('urlsSized({\"sizes\":{\"height\":219,\"width\":390}})') or
                                  art[art_key].get('urlsSized({\"sizes\":{\"height\":153,\"width\":360}})'))
                    if urls_sized and len(urls_sized) > 0:
                        poster = urls_sized[0].get('url')
                        break

            logo_url = None
            if art.get('logoArt'):
                urls_sized = (art['logoArt'].get('urlsSized({\"sizes\":{\"height\":675,\"width\":1200}})') or
                              art['logoArt'].get('urlsSized({\"sizes\":{\"height\":219,\"width\":390}})') or
                              art['logoArt'].get('urlsSized({\"sizes\":{\"height\":153,\"width\":360}})'))
                if urls_sized and len(urls_sized) > 0:
                    logo_url = urls_sized[0].get('url')

            mapping[title.lower().strip()] = {
                'netflix_id': vid,
                'title': title,
                'show_title': show_title,
                'season_title': season_title,
                'release_year': release_year,
                'synopsis': synopsis,
                'maturity_rating': maturity_rating,
                'runtime_seconds': runtime_seconds,
                'poster_url': poster,
                'logo_url': logo_url
            }
    return mapping

def fetch_local_title(netflix_id: int, country_code: str) -> str | None:
    if not netflix_id:
        return None
    cc = country_code.lower()
    if cc == 'global':
        cc = 'tr'
    url = f"https://www.netflix.com/{cc}/title/{netflix_id}"
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Accept-Language': f'{cc}-{cc.upper()},{cc};q=0.9,en-US;q=0.8,en;q=0.7'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode('utf-8')
    except http.client.IncompleteRead as e:
        html = e.partial.decode('utf-8', errors='ignore')
    except Exception:
        return None

    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL)
    if h1:
        clean = re.sub(r'<[^>]+>', '', h1.group(1)).strip()
        if clean:
            return clean
    return None

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
                country_name = row.get('country_name', '').strip() or country_iso
                formats_allowed = config_map[country_iso]
            else:
                if 'GLOBAL' not in config_map:
                    continue
                country_code = 'GLOBAL'
                country_name = 'Global'
                formats_allowed = config_map['GLOBAL']
                
            # Category Mapping
            raw_category = row.get('category', '')
            if raw_category.startswith('Films'):
                category = 'Movies'
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
            if season_title == 'N/A':
                season_title = None
            
            if season_title:
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
            
            # Extract views and hours for ranking
            views = 0
            try:
                views = int(row.get('weekly_views') or 0)
            except ValueError:
                views = 0
                
            hours = 0
            try:
                hours = int(row.get('weekly_hours_viewed') or 0)
            except ValueError:
                hours = 0

            cum_weeks = 0
            try:
                cum_weeks = int(row.get('cumulative_weeks_in_top_10') or 0)
            except ValueError:
                cum_weeks = 0

            runtime_seconds = None
            raw_runtime = row.get('runtime')
            if raw_runtime:
                try:
                    runtime_seconds = int(float(raw_runtime) * 3600)
                except ValueError:
                    runtime_seconds = None

            # Rank
            try:
                rank = int(row.get('weekly_rank', '0'))
            except ValueError:
                rank = 0

            parsed_results.append({
                'country_code': country_code,
                'country_name': country_name,
                'category': category,
                'rank': rank,
                'title': title,
                'show_title': show_title,
                'season_title': season_title,
                'type': item_type,
                'release_year': year,
                'season_name': season_name,
                'folder_name': folder_name,
                'views': views,
                'hours': hours,
                'cumulative_weeks': cum_weeks,
                'runtime_seconds': runtime_seconds
            })
            
    if not is_country_tsv:
        final_results = []
        for cat in ['Movies', 'TV']:
            cat_items = [item for item in parsed_results if item['category'] == cat]
            cat_items.sort(key=lambda x: (x['views'], x['hours']), reverse=True)
            top10 = cat_items[:10]
            for idx, item in enumerate(top10):
                item['rank'] = idx + 1
                final_results.append(item)
        return final_results
        
    return parsed_results

def crawl_netflix_top10(db_path: str, current_task_start: int = 1, total_tasks: int = 0):
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
    
    metadata_cache = {}
    current_task = current_task_start
    
    # Process Global rankings
    if global_config:
        set_crawl_progress(0, total_tasks, "Fetching Global Top 10 rankings")
        global_url = "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv"
        global_path = os.path.join(cache_dir, "all-weeks-global.tsv")
        fetch_top10_tsv(global_url, global_path)
        
        latest_week = get_latest_available_week(global_path)
        if latest_week:
            parsed_data = parse_top10_data(global_path, global_config, latest_week)
            meta_map = fetch_country_top10_metadata('GLOBAL')
            
            # Clear rankings only for GLOBAL and target week atomically right before insertion
            clear_rankings_for_country_and_week(db_path, 'GLOBAL', latest_week)
            
            for item in parsed_data:
                meta = meta_map.get(item['title'].lower().strip(), {})
                poster_url = meta.get('poster_url')
                logo_url = meta.get('logo_url')
                netflix_id = meta.get('netflix_id')
                local_title = fetch_local_title(netflix_id, 'GLOBAL') if netflix_id else None

                show_title = meta.get('show_title') or item.get('show_title')
                season_title = meta.get('season_title') or item.get('season_title')
                synopsis = meta.get('synopsis')
                maturity_rating = meta.get('maturity_rating')
                runtime_seconds = meta.get('runtime_seconds') or item.get('runtime_seconds')

                media_item_id = upsert_media_item(
                    db_path,
                    title=item['title'],
                    type=item['type'],
                    release_year=item['release_year'],
                    season_name=item['season_name'],
                    folder_name=item['folder_name'],
                    local_title=local_title,
                    netflix_id=netflix_id,
                    show_title=show_title,
                    season_title=season_title,
                    synopsis=synopsis,
                    maturity_rating=maturity_rating,
                    runtime_seconds=runtime_seconds,
                    logo_url=logo_url,
                    poster_url=poster_url
                )

                insert_ranking(
                    db_path,
                    country_code=item['country_code'],
                    country_name=item.get('country_name', 'Global'),
                    category=item['category'],
                    rank=item['rank'],
                    week=latest_week,
                    media_item_id=media_item_id,
                    weekly_hours_viewed=item['hours'],
                    weekly_views=item['views'],
                    cumulative_weeks_in_top_10=item['cumulative_weeks']
                )
                
    # Process Country rankings
    if country_configs:
        countries_url = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
        countries_path = os.path.join(cache_dir, "all-weeks-countries.tsv")
        fetch_top10_tsv(countries_url, countries_path)
        
        latest_week = get_latest_available_week(countries_path)
        if latest_week:
            parsed_data = parse_top10_data(countries_path, country_configs, latest_week)
            
            # Group parsed items by country_code to update each country atomically
            country_groups = {}
            for item in parsed_data:
                cc = item['country_code']
                country_groups.setdefault(cc, []).append(item)
                
            for cc, items in country_groups.items():
                set_crawl_progress(0, total_tasks, f"Fetching Top 10 rankings for {cc}")

                if cc not in metadata_cache:
                    metadata_cache[cc] = fetch_country_top10_metadata(cc)
                meta_map = metadata_cache[cc]
                
                # Clear rankings specifically for this country and target week right before inserting
                clear_rankings_for_country_and_week(db_path, cc, latest_week)

                for item in items:
                    meta = meta_map.get(item['title'].lower().strip(), {})
                    poster_url = meta.get('poster_url')
                    logo_url = meta.get('logo_url')
                    netflix_id = meta.get('netflix_id')
                    local_title = fetch_local_title(netflix_id, cc) if netflix_id else None

                    show_title = meta.get('show_title') or item.get('show_title')
                    season_title = meta.get('season_title') or item.get('season_title')
                    synopsis = meta.get('synopsis')
                    maturity_rating = meta.get('maturity_rating')
                    runtime_seconds = meta.get('runtime_seconds') or item.get('runtime_seconds')

                    media_item_id = upsert_media_item(
                        db_path,
                        title=item['title'],
                        type=item['type'],
                        release_year=item['release_year'],
                        season_name=item['season_name'],
                        folder_name=item['folder_name'],
                        local_title=local_title,
                        netflix_id=netflix_id,
                        show_title=show_title,
                        season_title=season_title,
                        synopsis=synopsis,
                        maturity_rating=maturity_rating,
                        runtime_seconds=runtime_seconds,
                        logo_url=logo_url,
                        poster_url=poster_url
                    )

                    insert_ranking(
                        db_path,
                        country_code=item['country_code'],
                        country_name=item.get('country_name'),
                        category=item['category'],
                        rank=item['rank'],
                        week=latest_week,
                        media_item_id=media_item_id,
                        weekly_hours_viewed=item['hours'],
                        weekly_views=item['views'],
                        cumulative_weeks_in_top_10=item['cumulative_weeks']
                    )
                current_task += 1


