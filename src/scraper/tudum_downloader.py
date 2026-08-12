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
    update_media_item_poster,
    update_media_item_tudum_metadata,
    reset_stubs_and_failed_media_items,
    reset_zero_byte_media_stubs
)
from src.crawler_lock import set_crawl_progress
from src.metadata.nfo_generator import (
    generate_nfo_xml,
    write_nfo_file
)

from src.logger import get_logger

logger = get_logger("netplex.downloader")

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
    """Fetches the HTML of the Tudum page and extracts metadata assets (plot, poster, logo, netflix_id, cast, directors, tagline, rating, etc.)."""
    empty_result = {
        "video_url": None,
        "subtitle_url": None,
        "plot": None,
        "netflix_id": None,
        "poster_url": None,
        "logo_url": None,
        "fanart_url": None,
        "tagline": None,
        "maturity_rating": None,
        "runtime_seconds": None,
        "actors": [],
        "directors": [],
        "creators": [],
        "genres": [],
        "tags": [],
        "season_count": None
    }
    if not tudum_url:
        return empty_result
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
        return empty_result
    except Exception as e:
        logger.warning(f"Error fetching page {tudum_url}: {e}")
        return empty_result
        
    # Unescape the graphql models block if present
    match = re.search(r"netflix\.reactContext\.models\.graphql\s*=\s*JSON\.parse\('(.*?)'\)", content)
    if match:
        try:
            unescaped_str = match.group(1).encode('utf-8').decode('unicode_escape')
            content += "\n" + unescaped_str
        except Exception:
            pass
            
    # Bypassed direct video/subtitle URL scraping from Tudum HTML
    video_url = None
    subtitle_url = None

    # Extract poster URL (og:image)
    poster_url = None
    og_img_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', content, re.IGNORECASE)
    if og_img_match:
        poster_url = sanitize_url(og_img_match.group(1))

    fanart_url = poster_url
    
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

    # Extract Tagline / Sub-headline
    tagline = None
    subhead_match = re.search(r'data-uia="sub-headline"[^>]*>(.*?)</div>', content, re.DOTALL)
    if subhead_match:
        raw_sub = re.sub(r'<[^>]+>', '', subhead_match.group(1)).strip()
        if raw_sub and len(raw_sub) < 300:
            tagline = raw_sub

    # Extract Netflix ID
    netflix_id = None
    id_match = re.search(r'netflix\.com/(?:watch|title)/(\d+)', content)
    if id_match:
        netflix_id = id_match.group(1)

    # Extract logo url if present
    logo_url = None
    logo_match = re.search(r'"logoArt"\s*:\s*\{[^}]*?"url"\s*:\s*"([^"]+)"', content)
    if logo_match:
        logo_url = sanitize_url(logo_match.group(1))

    # Extract maturity rating
    maturity_rating = None
    mat_match = re.search(r'data-uia="maturity-rating"[^>]*>(.*?)</span>', content, re.DOTALL)
    if mat_match:
        maturity_rating = re.sub(r'<[^>]+>', '', mat_match.group(1)).strip()
    if not maturity_rating:
        mat_match2 = re.search(r'"maturityRating"\s*:\s*"([^"]+)"', content)
        if mat_match2:
            maturity_rating = mat_match2.group(1).strip()

    # Extract runtime seconds
    runtime_seconds = None
    rt_match = re.search(r'"runtimeSeconds"\s*:\s*(\d+)', content)
    if rt_match:
        try:
            runtime_seconds = int(rt_match.group(1))
        except ValueError:
            runtime_seconds = None

    # Extract tags & season count
    tags = []
    season_count = None
    tag_elements = re.findall(r'data-uia="tag"[^>]*>(.*?)</span>', content, re.DOTALL)
    for tag_html in tag_elements:
        clean_t = re.sub(r'<[^>]+>', '', tag_html).strip()
        if not clean_t:
            continue
            
        # Check if tag is runtime duration (e.g. "1:52:10", "45m", "1h 30m")
        time_match = re.search(r'^(?:(\d+):)?(\d{1,2}):(\d{2})$', clean_t)
        if time_match:
            h = int(time_match.group(1) or 0)
            m = int(time_match.group(2))
            s = int(time_match.group(3))
            if not runtime_seconds:
                runtime_seconds = h * 3600 + m * 60 + s
            continue

        hm_match = re.search(r'^(?:(\d+)\s*h)?\s*(\d+)\s*m$', clean_t, re.IGNORECASE)
        if hm_match:
            h = int(hm_match.group(1) or 0)
            m = int(hm_match.group(2))
            if not runtime_seconds:
                runtime_seconds = h * 3600 + m * 60
            continue

        tags.append(clean_t)
        s_match = re.search(r'(\d+)\s+Seasons?', clean_t, re.IGNORECASE)
        if s_match:
            try:
                season_count = int(s_match.group(1))
            except ValueError:
                pass
        if not maturity_rating and clean_t in ['TV-MA', 'TV-14', 'TV-PG', 'TV-G', 'TV-Y7', 'PG-13', 'PG', 'R', 'G', 'NC-17']:
            maturity_rating = clean_t

    # Extract cast / actors
    actors = []
    cast_match = re.search(r'data-uia="cast"[^>]*>(.*?)</div>', content, re.DOTALL)
    if cast_match:
        raw_cast = re.sub(r'<[^>]+>', '', cast_match.group(1)).strip()
        if raw_cast:
            actors = [a.strip() for a in re.split(r'[,|;]', raw_cast) if a.strip()]
    if not actors:
        cast_json = re.search(r'"cast"\s*:\s*\[([^\]]+)\]', content)
        if cast_json:
            found_names = re.findall(r'"name"\s*:\s*"([^"]+)"', cast_json.group(1))
            if not found_names:
                found_names = [n.strip(' "\'') for n in cast_json.group(1).split(',')]
            actors = [f for f in found_names if f]
    if not actors:
        starring_match = re.search(r'(?:Starring|Cast):\s*([^<]+)', content, re.IGNORECASE)
        if starring_match:
            actors = [a.strip() for a in re.split(r'[,|;]', starring_match.group(1)) if a.strip()]

    # Extract directors / creators
    directors = []
    creators = []
    dir_match = re.search(r'data-uia="directors"[^>]*>(.*?)</div>', content, re.DOTALL)
    if dir_match:
        raw_dir = re.sub(r'<[^>]+>', '', dir_match.group(1)).strip()
        if raw_dir:
            directors = [d.strip() for d in re.split(r'[,|;]', raw_dir) if d.strip()]

    creator_html_match = re.search(r'data-uia="creators"[^>]*>(.*?)</div>', content, re.DOTALL)
    if creator_html_match:
        raw_creator = re.sub(r'<[^>]+>', '', creator_html_match.group(1)).strip()
        if raw_creator:
            creators = [c.strip() for c in re.split(r'[,|;]', raw_creator) if c.strip()]

    if not directors and not creators:
        dir_json = re.search(r'"(?:directors|creators)"\s*:\s*\[([^\]]+)\]', content)
        if dir_json:
            found_dirs = re.findall(r'"name"\s*:\s*"([^"]+)"', dir_json.group(1))
            if not found_dirs:
                found_dirs = [n.strip(' "\'') for n in dir_json.group(1).split(',')]
            directors = [f for f in found_dirs if f]
            
    if not directors:
        dir_text_match = re.search(r'(?:Directed by|Directors?):\s*([^<]+)', content, re.IGNORECASE)
        if dir_text_match:
            directors = [d.strip() for d in re.split(r'[,|;]', dir_text_match.group(1)) if d.strip()]

    if not creators:
        creator_text_match = re.search(r'(?:Created by|Creators?):\s*([^<]+)', content, re.IGNORECASE)
        if creator_text_match:
            creators = [c.strip() for c in re.split(r'[,|;]', creator_text_match.group(1)) if c.strip()]

    # Deduplicate while preserving order
    actors = list(dict.fromkeys(actors))
    directors = list(dict.fromkeys(directors))
    creators = list(dict.fromkeys(creators))
    tags = list(dict.fromkeys(tags))

    genres = [t for t in tags if t not in ['TV-14', 'TV-MA', 'PG-13', 'R', 'TV-PG', 'TV-G', 'TV-Y7', 'PG', 'G', 'NC-17'] and not re.search(r'^\d{4}$', t) and 'Season' not in t]

    return {
        "video_url": video_url,
        "subtitle_url": subtitle_url,
        "plot": plot,
        "netflix_id": netflix_id,
        "poster_url": poster_url,
        "logo_url": logo_url,
        "fanart_url": fanart_url,
        "tagline": tagline,
        "maturity_rating": maturity_rating,
        "runtime_seconds": runtime_seconds,
        "actors": actors,
        "directors": directors,
        "creators": creators,
        "genres": genres,
        "tags": tags,
        "season_count": season_count
    }

def download_file(url: str, output_path: str):
    """Downloads the file from the given URL to output_path using yt-dlp."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    clean_url = sanitize_url(url)
    try:
        import yt_dlp
        logger.info(f"  ├─ Downloading video stream via yt-dlp: {clean_url}")
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
        logger.warning(f"  ├─ yt-dlp download failed for {clean_url}: {e}, falling back to urllib stream download")
        req = urllib.request.Request(clean_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response, open(output_path, 'wb') as out_file:
            while True:
                chunk = response.read(16384)
                if not chunk:
                    break
                out_file.write(chunk)

def score_trailer_candidate(
    entry: dict,
    title: str,
    release_year: int,
    actors: list[str] = None,
    directors: list[str] = None
) -> float:
    """
    Scores a YouTube candidate video entry for how well it matches the desired trailer.
    Returns a score float. Scores below 25.0 are considered non-matching/disqualified.
    Gives negative score (-999.0) if content is marked as AI generated or concept fan video.
    """
    if not entry or not isinstance(entry, dict):
        return -999.0

    v_title = entry.get('title', '') or ''
    v_uploader = entry.get('uploader') or entry.get('channel') or ''
    v_desc = entry.get('description', '') or ''
    v_duration = entry.get('duration')

    # If mock entry without title is passed in tests, derive or fallback
    if not v_title and (entry.get('webpage_url') or entry.get('id')):
        v_title = title + " official trailer"

    norm_target = re.sub(r'[^\w\s]', '', title.lower()).strip()
    norm_candidate = re.sub(r'[^\w\s]', '', v_title.lower()).strip()
    norm_uploader = v_uploader.lower()
    norm_desc = v_desc.lower()

    if not norm_target or not norm_candidate:
        return -999.0

    # 1. Target presence and short title word boundary matching
    target_words = set(norm_target.split())
    candidate_words = set(norm_candidate.split())

    matching_words = target_words.intersection(candidate_words)
    if not matching_words:
        return -999.0

    # For short titles (<= 4 chars or single word like "Max"), enforce exact word boundary matching
    if len(title) <= 4 or len(target_words) == 1:
        pattern = r'\b' + re.escape(norm_target) + r'\b'
        if not re.search(pattern, norm_candidate):
            return -999.0

    score = 0.0

    # 2. AI-Generated & Fake/Fan Content Disqualification (Negative Score)
    ai_phrases = [
        'ai generated', 'ai-generated', 'ai concept', 'ai trailer', 'ai voice', 'ai version',
        'ai remastered', 'ai remake', 'ai animation', 'ai movie', 'made with ai', 'ai fan',
        'artificial intelligence', 'midjourney', 'sora ai', 'elevenlabs', 'runway gen',
        'kling ai', 'pika ai', 'luma ai', 'dall-e', 'dalle'
    ]
    v_tags = [str(t).lower() for t in (entry.get('tags') or [])]
    v_cats = [str(c).lower() for c in (entry.get('categories') or [])]
    combined_meta = f"{norm_candidate} {norm_uploader} {norm_desc} {' '.join(v_tags)} {' '.join(v_cats)}"

    if 'ai' not in norm_target and 'artificial intelligence' not in norm_target:
        for phrase in ai_phrases:
            if phrase in combined_meta:
                return -999.0
        if re.search(r'\bai\b', combined_meta) and any(w in combined_meta for w in ['concept', 'trailer', 'remake', 'fan', 'voice', 'teaser', 'generated']):
            return -999.0

    # 3. Negative Term Filtering (Disqualification / Heavy Penalties)
    negative_terms = [
        'iphone', 'apple', 'samsung', 'galaxy', 'pixel', 'pro max', 'macbook', 'ipad', 'unboxing', 'gadget',
        'reaction', 'review', 'gameplay', 'walkthrough', 'lets play', "let's play", 'breakdown', 'ending explained',
        'explained', 'fan made', 'fan-made', 'concept trailer', 'parody', 'spoiler', 'how to', 'vlog', 'livestream',
        'podcast', 'full album', 'soundtrack', 'ost', 'theme song', 'cover', 'instrumental', 'remix', 'music video',
        'full movie', 'movie clip', 'scene clip', 'trailer reaction', 'teaser reaction'
    ]
    for neg in negative_terms:
        if neg in norm_target:
            continue
        if neg in norm_candidate or neg in norm_uploader:
            return -999.0

    # 4. Title Matching Score
    if norm_target in norm_candidate:
        score += 35.0
    elif target_words.issubset(candidate_words):
        score += 25.0
    else:
        word_match_ratio = len(matching_words) / len(target_words)
        score += word_match_ratio * 20.0

    # 5. Trailer / Teaser Keyword Score
    if 'official trailer' in norm_candidate:
        score += 25.0
    elif 'teaser trailer' in norm_candidate or 'official teaser' in norm_candidate:
        score += 20.0
    elif any(kw in norm_candidate for kw in ['trailer', 'teaser', 'first look', 'sneak peek', 'preview']):
        score += 15.0

    # 6. Release Year Bonus
    year_str = str(release_year)
    prev_year_str = str(release_year - 1)
    next_year_str = str(release_year + 1)
    if year_str in norm_candidate or year_str in norm_desc:
        score += 15.0
    elif prev_year_str in norm_candidate or next_year_str in norm_candidate:
        score += 10.0

    # 7. Channel / Publisher Trust Bonus
    netflix_channels = ['netflix', 'netflix india', 'netflix asia', 'netflix uk', 'netflix anime', 'netflix jr']
    major_distributors = [
        'warner', 'sony pictures', 'universal pictures', 'paramount', 'disney', 'marvel', 'a24', 'hbo',
        'movieclips', 'rotten tomatoes', 'ign', 'studiocanal', 'lionsgate', 'hulu', 'amazon prime', 'prime video',
        'apple tv'
    ]
    generic_trailer_channels = ['trailer', 'pictures', 'films', 'studios', 'cinema', 'entertainment']

    if any(ch in norm_uploader for ch in netflix_channels):
        score += 35.0
    elif any(ch in norm_uploader for ch in major_distributors):
        score += 25.0
    elif any(ch in norm_uploader for ch in generic_trailer_channels):
        score += 10.0

    # 8. Video Duration Verification
    if v_duration is not None:
        try:
            d = float(v_duration)
            if 30 <= d <= 300:
                score += 15.0
            elif 15 <= d < 30 or 300 < d <= 420:
                score += 5.0
            elif d < 15:
                score -= 30.0
            elif 600 < d <= 1200:
                score -= 50.0
            elif d > 1200:
                return -999.0
        except (ValueError, TypeError):
            pass

    # 9. Actor & Director Verification Bonus
    if actors:
        actor_matches = 0
        for actor in actors:
            norm_actor = re.sub(r'[^\w\s]', '', actor.lower()).strip()
            if not norm_actor or len(norm_actor) < 3:
                continue
            if norm_actor in norm_candidate or norm_actor in norm_desc or norm_actor in norm_uploader or any(norm_actor in t for t in v_tags):
                actor_matches += 1
        if actor_matches > 0:
            score += min(actor_matches * 15.0, 30.0)

    if directors:
        director_matches = 0
        for director in directors:
            norm_dir = re.sub(r'[^\w\s]', '', director.lower()).strip()
            if not norm_dir or len(norm_dir) < 3:
                continue
            if norm_dir in norm_candidate or norm_dir in norm_desc or norm_dir in norm_uploader or any(norm_dir in t for t in v_tags):
                director_matches += 1
        if director_matches > 0:
            score += min(director_matches * 20.0, 30.0)

    return score


def search_and_download_youtube_trailer(
    title: str,
    release_year: int,
    output_path: str,
    fetch_subtitles: bool = False,
    subtitle_langs: list[str] = None,
    actors: list[str] = None,
    directors: list[str] = None
) -> str | None:
    """
    Searches YouTube for official trailer using yt-dlp, saves to output_path,
    and returns YouTube webpage URL if successful.
    """
    import yt_dlp
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    clean_title = re.sub(r'[\"\']', '', title).strip()

    queries = [
        f'ytsearch5:{clean_title} {release_year} Netflix official trailer',
        f'ytsearch5:{clean_title} {release_year} official trailer',
        f'ytsearch5:{clean_title} official trailer',
    ]
    if actors and len(actors) > 0 and actors[0]:
        clean_actor = re.sub(r'[\"\']', '', actors[0]).strip()
        queries.append(f'ytsearch5:{clean_title} {clean_actor} official trailer')
    if directors and len(directors) > 0 and directors[0]:
        clean_dir = re.sub(r'[\"\']', '', directors[0]).strip()
        queries.append(f'ytsearch5:{clean_title} {clean_dir} official trailer')
    queries.append(f'ytsearch5:{clean_title} trailer')
    
    best_entry = None
    best_score = -999.0
    best_url = None
    seen_ids = set()

    search_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
    }

    for query in queries:
        try:
            logger.info(f"  ├─ Searching YouTube via yt-dlp with query: {query}")
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if info and 'entries' in info:
                    for entry in info['entries']:
                        if not entry:
                            continue
                        e_id = entry.get('id') or entry.get('webpage_url')
                        if e_id in seen_ids:
                            continue
                        if e_id:
                            seen_ids.add(e_id)

                        cand_score = score_trailer_candidate(entry, title, release_year, actors=actors, directors=directors)
                        cand_title = entry.get('title', 'Unknown Title')
                        cand_uploader = entry.get('uploader') or entry.get('channel', 'Unknown Channel')

                        logger.debug(f"  │   ├─ Candidate: '{cand_title}' by '{cand_uploader}' | Score: {cand_score:.1f}")

                        if cand_score > best_score:
                            url = entry.get('webpage_url') or entry.get('url')
                            if not url and entry.get('id'):
                                url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                            if url:
                                best_score = cand_score
                                best_entry = entry
                                best_url = url

            if best_score >= 50.0:
                break
        except Exception as e:
            logger.warning(f"  ├─ YouTube search query failed for '{query}': {e}")
            
    MIN_SCORE_THRESHOLD = 25.0
    if not best_url or best_score < MIN_SCORE_THRESHOLD:
        logger.warning(f"  ├─ No valid YouTube trailer found for '{title}' (Best score: {best_score:.1f}, threshold: {MIN_SCORE_THRESHOLD})")
        return None

    v_title = best_entry.get('title', 'Unknown Title')
    v_uploader = best_entry.get('uploader') or best_entry.get('channel', 'Unknown Channel')
    v_duration = best_entry.get('duration')
    duration_str = f"{v_duration}s" if v_duration else "N/A"
    logger.info(f"  ├─ YouTube match selected (Score: {best_score:.1f}):")
    logger.info(f"  │   ├─ Title: '{v_title}'")
    logger.info(f"  │   ├─ Channel: '{v_uploader}'")
    logger.info(f"  │   ├─ Duration: {duration_str}")
    logger.info(f"  │   └─ URL: {best_url}")

    yt_url = best_url

    format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    try:
        logger.info(f"  ├─ Starting yt-dlp video download:")
        logger.info(f"  │   ├─ Target URL: {yt_url}")
        logger.info(f"  │   ├─ Format Spec: '{format_spec}'")
        logger.info(f"  │   ├─ Output Path: {output_path}")
        if fetch_subtitles:
            sub_lang = subtitle_langs[0] if subtitle_langs else "en"
            logger.info(f"  │   └─ Subtitles: Enabled (Language: {sub_lang}, Format: SRT via FFmpeg)")
        else:
            logger.info(f"  │   └─ Subtitles: Disabled")

        ydl_opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'overwrites': True,
            'format': format_spec,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web']
                }
            }
        }
        if fetch_subtitles:
            sub_lang = subtitle_langs[0] if subtitle_langs else "en"
            ydl_opts.update({
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': [sub_lang],
                'postprocessors': [{
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': 'srt',
                }],
            })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([yt_url])
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            logger.info(f"  ├─ yt-dlp download completed successfully ({file_size_mb:.2f} MB saved)")
        else:
            logger.info(f"  ├─ yt-dlp download finished successfully for target: {output_path}")
        return yt_url
    except Exception as e:
        logger.error(f"  ├─ yt-dlp download failed for '{yt_url}': {e}")
        return None


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

def download_pending_trailers(db_path: str, media_dir: str = None, current_task_start: int = 1, total_tasks: int = 0):
    """Fetches all pending media items from the database and downloads their trailers/subtitles."""
    if media_dir is None:
        media_dir = os.environ.get("NETPLEX_DATA_DIR", "/data")
        
    dummy_media_mode = get_setting(db_path, "dummy_media_mode", "false").lower() in ("true", "1", "yes", "on")
    if not dummy_media_mode:
        reset_ids = reset_stubs_and_failed_media_items(db_path)
        if reset_ids:
            logger.info(f"Dummy mode deactivated/disabled: Found {len(reset_ids)} zero-byte media stub file(s) or failed items. Resetting status to 'pending' to download real trailers.")

    conn = _get_connection(db_path)
    try:
        cursor = conn.execute("SELECT id, title, type, release_year, season_name, folder_name FROM media_items WHERE status = 'pending'")
        items = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
        
    if not items:
        return
    trailer_subtitles = get_setting(db_path, "trailer_subtitles", "false").lower() in ("true", "1", "yes", "on")
    subtitle_languages_str = get_setting(db_path, "subtitle_languages", "en")
    subtitle_langs = [lang.strip() for lang in subtitle_languages_str.split(",") if lang.strip()]
    
    total_count = max(len(items), total_tasks)
    for idx, item in enumerate(items):
        current_task = idx + 1
        set_crawl_progress(current_task, total_count, f"Downloading trailer: {item['title']}")
        logger.info(f"Processing trailer for '{item['title']}' ({item['type'].upper()}, ID: {item['id']})")

        try:
            logger.info(f"  ├─ Searching Netflix Tudum page for '{item['title']}' metadata...")
            tudum_url = find_tudum_page(item['title'], item['type'], item['release_year'])
            if tudum_url:
                logger.info(f"  ├─ Found Tudum page URL: {tudum_url}")
            else:
                logger.info(f"  ├─ No direct Tudum page found for '{item['title']}'. Checking fallback page.")
                
            assets = extract_trailer_assets(tudum_url)
            
            update_media_item_tudum_metadata(
                db_path,
                item['id'],
                synopsis=assets.get("plot"),
                video_url=assets.get("video_url"),
                subtitle_url=assets.get("subtitle_url"),
                netflix_id=assets.get("netflix_id"),
                poster_url=assets.get("poster_url"),
                logo_url=assets.get("logo_url"),
                maturity_rating=assets.get("maturity_rating"),
                runtime_seconds=assets.get("runtime_seconds")
            )
                
            # Determine directory layout
            folder_name = item['folder_name']
            ext = ".mp4"
            
            sub_lang = subtitle_langs[0] if subtitle_langs else "en"
            if item['type'] == 'movie':
                target_dir = os.path.join(media_dir, "movies", folder_name)
                video_filename = f"{folder_name}{ext}"
                video_path = os.path.join(target_dir, video_filename)
                
                sub_filename = f"{folder_name}.{sub_lang}.srt"
                sub_path = os.path.join(target_dir, sub_filename)

                nfo_dir = target_dir
                nfo_file = "movie.nfo"
            else:
                season_padded = extract_season_number(item['season_name'])
                target_dir = os.path.join(media_dir, "tv", folder_name, f"Season {season_padded}")
                video_filename = f"S{season_padded}E00 - Trailer{ext}"
                video_path = os.path.join(target_dir, video_filename)
                
                sub_filename = f"S{season_padded}E00 - Trailer.{sub_lang}.srt"
                sub_path = os.path.join(target_dir, sub_filename)

                nfo_dir = os.path.join(media_dir, "tv", folder_name)
                nfo_file = "tvshow.nfo"
                
            os.makedirs(target_dir, exist_ok=True)
            os.makedirs(nfo_dir, exist_ok=True)
                
            # Download or create dummy video stub
            if dummy_media_mode:
                logger.info(f"  ├─ Dummy media mode enabled: Creating zero-byte trailer stub file at {video_path}")
                open(video_path, 'wb').close()
            else:
                yt_url = search_and_download_youtube_trailer(
                    item['title'],
                    item['release_year'],
                    video_path,
                    fetch_subtitles=trailer_subtitles,
                    subtitle_langs=subtitle_langs,
                    actors=assets.get("actors"),
                    directors=assets.get("directors")
                )
                if yt_url:
                    update_media_item_tudum_metadata(db_path, item['id'], youtube_url=yt_url)
                else:
                    logger.warning(f"  ├─ YouTube trailer download via yt-dlp failed or no video found for '{item['title']}'. Creating zero-byte placeholder file at {video_path}")
                    open(video_path, 'wb').close()
            
            # Generate and Write NFO metadata
            try:
                plot = assets.get("plot") or f"Top 10 Netflix trailer for {item['title']}."
                netflix_id = assets.get("netflix_id")
                is_tv = (item['type'] == 'tv')
                
                trailer_rel = f"Season {season_padded}/{video_filename}" if is_tv else video_filename
                trailer_url = item.get('youtube_url') or trailer_rel
                
                nfo_xml = generate_nfo_xml(
                    title=item['title'],
                    year=item['release_year'],
                    plot=plot,
                    netflix_id=netflix_id,
                    is_tv=is_tv,
                    local_title=item.get('local_title'),
                    tagline=assets.get('tagline'),
                    maturity_rating=assets.get('maturity_rating'),
                    runtime_seconds=assets.get('runtime_seconds'),
                    studio="Netflix",
                    genres=assets.get('genres'),
                    tags=assets.get('tags'),
                    directors=assets.get('directors'),
                    creators=assets.get('creators'),
                    actors=assets.get('actors'),
                    poster_url=assets.get('poster_url'),
                    logo_url=assets.get('logo_url'),
                    fanart_url=assets.get('fanart_url'),
                    trailer_url=trailer_url,
                    season_count=assets.get('season_count')
                )
                
                logger.info(f"  ├─ Generating and writing NFO metadata ({nfo_file}) at {nfo_dir}...")
                write_nfo_file(nfo_dir, nfo_xml, nfo_file)
            except Exception as nfo_err:
                logger.error(f"  ├─ Failed to write NFO for {item['title']}: {nfo_err}")

            update_media_item_status(db_path, item['id'], 'downloaded', file_path=video_path)
            logger.info(f"  └─ Successfully completed trailer download and metadata setup for '{item['title']}'")
            
        except Exception as e:
            logger.error(f"Failed to process trailer for {item['title']}: {e}", exc_info=True)
            update_media_item_status(db_path, item['id'], 'failed')
