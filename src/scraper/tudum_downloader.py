import os
import re
import datetime
import urllib.request
import http.client
import logging
from src.database import (
    _get_connection,
    get_setting,
    update_media_item_status,
    update_media_item_poster
)
from src.metadata.nfo_generator import (
    generate_nfo_xml,
    write_nfo_file
)

import urllib.parse
import urllib.error

logger = logging.getLogger(__name__)

def make_slug(title: str) -> str:
    """Formats a title into a clean slug (lowercase, dashes instead of spaces, removes special characters)."""
    slug = title.lower()
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')

def sanitize_url(url: str) -> str:
    """Ensures URL has scheme/domain and handles URL encoding for spaces and control characters."""
    if not url:
        return url
    url = url.strip()
    if url.startswith('/'):
        url = f"https://www.netflix.com{url}"
    elif not url.startswith('http://') and not url.startswith('https://'):
        url = f"https://{url}"
        
    parts = urllib.parse.urlsplit(url)
    encoded_path = urllib.parse.quote(parts.path, safe='/:?&=#%')
    encoded_query = urllib.parse.quote(parts.query, safe='/:?&=#%')
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, encoded_path, encoded_query, parts.fragment))

def find_tudum_page(title: str, item_type: str, year: int) -> str | None:
    """Generates the direct URL on Netflix Tudum or scans Top 10 list page as fallback."""
    slug = make_slug(title)
    direct_url = f"https://www.netflix.com/tudum/{slug}"
    
    # Try fetching the direct URL first
    try:
        req = urllib.request.Request(direct_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return direct_url
    except Exception:
        pass
        
    # Fallback: scan Top 10 list page for matching link
    try:
        top10_url = "https://www.netflix.com/tudum/top10"
        req = urllib.request.Request(top10_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode('utf-8')
            links = re.findall(r'href="([^"]*/tudum/[^"]*)"', html)
            for link in links:
                if slug in link.lower():
                    if link.startswith('http'):
                        return link
                    cleaned_link = link.replace('/tudum', '')
                    return f"https://www.netflix.com/tudum{cleaned_link}"
    except Exception:
        pass
        
    return None

def extract_trailer_assets(tudum_url: str | None) -> dict:
    """Fetches the HTML of the Tudum page, extracts the unescaped graphql models, and locates media assets."""
    if not tudum_url:
        return {"video_url": None, "subtitle_url": None, "plot": None, "netflix_id": None, "poster_url": None}
    content = ""
    try:
        req = urllib.request.Request(tudum_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode('utf-8')
        except http.client.IncompleteRead as e:
            content = e.partial.decode('utf-8')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.info(f"Tudum page not found (404) for URL: {tudum_url}")
        else:
            logger.warning(f"HTTP Error {e.code} fetching {tudum_url}")
        return {"video_url": None, "subtitle_url": None, "plot": None, "netflix_id": None, "poster_url": None}
    except Exception as e:
        logger.warning(f"Error fetching page {tudum_url}: {e}")
        return {"video_url": None, "subtitle_url": None, "plot": None, "netflix_id": None, "poster_url": None}
        
    # Unescape the graphql models block if present
    match = re.search(r"netflix\.reactContext\.models\.graphql\s*=\s*JSON\.parse\('(.*?)'\)", content)
    if match:
        try:
            unescaped_str = match.group(1).encode('utf-8').decode('unicode_escape')
            content += "\n" + unescaped_str
        except Exception:
            pass
            
    # Find all double-quoted URLs containing .mp4 or .mkv
    video_urls = re.findall(r'"((?:https?://|/)[^"]+?\.(?:mp4|mkv)[^"]*)"', content)
    filtered_videos = [u for u in video_urls if "TudumSignIn_" not in u]
    video_url = sanitize_url(filtered_videos[0]) if filtered_videos else None
    
    # Find all double-quoted URLs containing .vtt or .srt
    subtitle_urls = re.findall(r'"((?:https?://|/)[^"]+?\.(?:vtt|srt)[^"]*)"', content)
    subtitle_url = sanitize_url(subtitle_urls[0]) if subtitle_urls else None

    # Extract poster URL (og:image)
    poster_url = None
    og_img_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', content, re.IGNORECASE)
    if og_img_match:
        poster_url = sanitize_url(og_img_match.group(1))
    
    # Extract synopsis / plot
    plot = None
    synopsis_match = re.search(r'data-uia="synopsis"[^>]*>(.*?)</div>', content, re.DOTALL)
    if synopsis_match:
        raw_plot = re.sub(r'<[^>]+>', '', synopsis_match.group(1)).strip()
        if raw_plot:
            plot = raw_plot
            
    if not plot:
        meta_match = re.search(r'<meta\s+[^>]*name="description"\s+content="([^"]+)"', content, re.IGNORECASE)
        if meta_match:
            plot = meta_match.group(1).strip()
            
    if not plot:
        og_match = re.search(r'<meta\s+[^>]*property="og:description"\s+content="([^"]+)"', content, re.IGNORECASE)
        if og_match:
            plot = og_match.group(1).strip()

    # Extract Netflix ID
    netflix_id = None
    id_match = re.search(r'netflix\.com/(?:watch|title)/(\d+)', content)
    if id_match:
        netflix_id = id_match.group(1)

    return {
        "video_url": video_url,
        "subtitle_url": subtitle_url,
        "plot": plot,
        "netflix_id": netflix_id,
        "poster_url": poster_url
    }

def download_file(url: str, output_path: str):
    """Downloads the file from the given URL to output_path using yt-dlp."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    clean_url = sanitize_url(url)
    try:
        import yt_dlp
        ydl_opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'overwrites': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([clean_url])
    except Exception as e:
        logger.warning(f"yt-dlp download failed for {clean_url}: {e}, falling back to urllib stream download")
        req = urllib.request.Request(clean_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response, open(output_path, 'wb') as out_file:
            while True:
                chunk = response.read(16384)
                if not chunk:
                    break
                out_file.write(chunk)


def convert_vtt_to_srt(vtt_content: str) -> str:
    """Converts WebVTT formatting timings and cue tags into standard SRT format."""
    # Normalize line endings
    vtt_content = vtt_content.replace('\r\n', '\n')
    lines = vtt_content.split('\n')
    
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("WEBVTT"):
            start_idx = i + 1
            break
            
    srt_blocks = []
    cue_idx = 1
    
    timestamp_pattern = re.compile(r'(\d{2}:\d{2}:\d{2})[.,](\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2})[.,](\d{3})')
    
    i = start_idx
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
            
        match = timestamp_pattern.search(line)
        if match:
            time_line = line
            text_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    break
                if timestamp_pattern.search(next_line):
                    break
                text_lines.append(next_line)
                i += 1
                
            # Clean VTT styles on timestamp line
            clean_time = timestamp_pattern.sub(r'\1,\2 --> \3,\4', time_line)
            clean_time_parts = clean_time.split(' ')
            if len(clean_time_parts) >= 3:
                clean_time = f"{clean_time_parts[0]} --> {clean_time_parts[2]}"
                
            # Clean VTT text tags
            clean_text_lines = []
            for tl in text_lines:
                tl_clean = re.sub(r'<[^>]+>', '', tl)
                if tl_clean.strip():
                    clean_text_lines.append(tl_clean)
                    
            srt_blocks.append(f"{cue_idx}\n{clean_time}\n" + "\n".join(clean_text_lines) + "\n")
            cue_idx += 1
        else:
            i += 1
            
    return "\n".join(srt_blocks)

def extract_season_number(season_name: str | None) -> str:
    """Extracts the season number (zero-padded to 2 digits). Handles digits ('Season 2'), word numbers ('Season Two'), and Roman numerals ('Season II'). Defaults to '01'."""
    if not season_name:
        return "01"
    
    # 1. Search for digits first
    match = re.search(r'\d+', season_name)
    if match:
        return f"{int(match.group(0)):02d}"
        
    # 2. Word numbers mapping
    word_map = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
    }
    for word, num in word_map.items():
        if re.search(r'\b' + word + r'\b', season_name, re.IGNORECASE):
            return f"{num:02d}"
            
    # 3. Roman numerals mapping
    roman_map = [
        (r'\bx\b', 10), (r'\bix\b', 9), (r'\bviii\b', 8), (r'\bvii\b', 7), (r'\bvi\b', 6),
        (r'\bv\b', 5), (r'\biv\b', 4), (r'\biii\b', 3), (r'\bii\b', 2), (r'\bi\b', 1)
    ]
    for pattern, num in roman_map:
        if re.search(pattern, season_name, re.IGNORECASE):
            return f"{num:02d}"
            
    return "01"

def download_pending_trailers(db_path: str, media_dir: str = None):
    """Fetches all pending media items from the database and downloads their trailers/subtitles."""
    if media_dir is None:
        media_dir = os.environ.get("NETPLEX_DATA_DIR", "/data")
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("SELECT id, title, type, release_year, season_name, folder_name FROM media_items WHERE status = 'pending'")
        items = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
        
    if not items:
        return
        
    trailer_subtitles = get_setting(db_path, "trailer_subtitles", "false") == "true"
    subtitle_languages_str = get_setting(db_path, "subtitle_languages", "en")
    subtitle_langs = [lang.strip() for lang in subtitle_languages_str.split(",") if lang.strip()]
    
    for item in items:
        logger.info(f"Processing trailer download for: {item['title']}")
        try:
            tudum_url = find_tudum_page(item['title'], item['type'], item['release_year'])
            assets = extract_trailer_assets(tudum_url)
            
            if assets.get("poster_url"):
                update_media_item_poster(db_path, item['id'], assets["poster_url"])

            if not assets["video_url"]:
                logger.warning(f"No video URL found for {item['title']}. Marking as failed.")
                update_media_item_status(db_path, item['id'], 'failed')
                continue
                
            # Determine directory layout
            folder_name = item['folder_name']
            
            if item['type'] == 'movie':
                target_dir = os.path.join(media_dir, "movies", folder_name)
                # Keep original extension or fallback to .mp4
                ext = ".mkv" if ".mkv" in assets["video_url"] else ".mp4"
                video_filename = f"{folder_name}{ext}"
                video_path = os.path.join(target_dir, video_filename)
                
                sub_lang = subtitle_langs[0] if subtitle_langs else "en"
                sub_filename = f"{folder_name}.{sub_lang}.srt"
                sub_path = os.path.join(target_dir, sub_filename)
            else:
                season_padded = extract_season_number(item['season_name'])
                target_dir = os.path.join(media_dir, "tv", folder_name, f"Season {season_padded}")
                ext = ".mkv" if ".mkv" in assets["video_url"] else ".mp4"
                video_filename = f"S{season_padded}E00 - Trailer{ext}"
                video_path = os.path.join(target_dir, video_filename)
                
                sub_lang = subtitle_langs[0] if subtitle_langs else "en"
                sub_filename = f"S{season_padded}E00 - Trailer.{sub_lang}.srt"
                sub_path = os.path.join(target_dir, sub_filename)
                
            os.makedirs(target_dir, exist_ok=True)
                
            # Download Video
            download_file(assets["video_url"], video_path)
            
            # Download Subtitle if enabled
            if trailer_subtitles and assets["subtitle_url"]:
                try:
                    req = urllib.request.Request(assets["subtitle_url"], headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=10) as response:
                        vtt_content = response.read().decode('utf-8')
                    srt_content = convert_vtt_to_srt(vtt_content)
                    with open(sub_path, "w", encoding="utf-8") as sf:
                        sf.write(srt_content)
                except Exception as sub_err:
                    logger.error(f"Failed to download/convert subtitle for {item['title']}: {sub_err}")
                    
            # Generate and Write NFO metadata
            try:
                plot = assets.get("plot") or f"Top 10 Netflix trailer for {item['title']}."
                netflix_id = assets.get("netflix_id")
                is_tv = (item['type'] == 'tv')
                
                nfo_xml = generate_nfo_xml(
                    title=item['title'],
                    year=item['release_year'],
                    plot=plot,
                    netflix_id=netflix_id,
                    is_tv=is_tv
                )
                
                if is_tv:
                    nfo_dir = os.path.join(media_dir, "tv", folder_name)
                    nfo_file = "tvshow.nfo"
                else:
                    nfo_dir = os.path.join(media_dir, "movies", folder_name)
                    nfo_file = "movie.nfo"
                    
                write_nfo_file(nfo_dir, nfo_xml, nfo_file)
            except Exception as nfo_err:
                logger.error(f"Failed to write NFO for {item['title']}: {nfo_err}")

            update_media_item_status(db_path, item['id'], 'downloaded', file_path=video_path)
            logger.info(f"Successfully downloaded trailer for {item['title']} to {video_path}")
            
        except Exception as e:
            logger.error(f"Failed to process trailer for {item['title']}: {e}", exc_info=True)
            update_media_item_status(db_path, item['id'], 'failed')
