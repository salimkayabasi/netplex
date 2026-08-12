import os
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger(__name__)

def generate_nfo_xml(
    title: str,
    year: int,
    plot: str,
    netflix_id: str | None = None,
    is_tv: bool = False,
    local_title: str | None = None,
    tagline: str | None = None,
    maturity_rating: str | None = None,
    runtime_seconds: int | None = None,
    studio: str | None = "Netflix",
    country: str | None = None,
    genres: list[str] | None = None,
    tags: list[str] | None = None,
    directors: list[str] | None = None,
    creators: list[str] | None = None,
    actors: list[str] | None = None,
    poster_url: str | None = None,
    logo_url: str | None = None,
    fanart_url: str | None = None,
    trailer_url: str | None = None,
    season_count: int | None = None
) -> str:
    """
    Generates standard Kodi/Plex/Jellyfin compatible XML metadata string for a movie or TV show.
    """
    root_tag = "tvshow" if is_tv else "movie"
    root = ET.Element(root_tag)
    
    title_el = ET.SubElement(root, "title")
    title_el.text = title
    
    if local_title and local_title != title:
        orig_title_el = ET.SubElement(root, "originaltitle")
        orig_title_el.text = local_title

    if tagline:
        tagline_el = ET.SubElement(root, "tagline")
        tagline_el.text = tagline
    
    year_el = ET.SubElement(root, "year")
    year_el.text = str(year)
    
    plot_el = ET.SubElement(root, "plot")
    plot_el.text = plot

    if tagline:
        outline_el = ET.SubElement(root, "outline")
        outline_el.text = tagline
    
    if maturity_rating:
        mpaa_el = ET.SubElement(root, "mpaa")
        mpaa_el.text = maturity_rating
        cert_el = ET.SubElement(root, "certification")
        cert_el.text = maturity_rating

    if runtime_seconds and runtime_seconds > 0:
        runtime_min = max(1, runtime_seconds // 60)
        runtime_el = ET.SubElement(root, "runtime")
        runtime_el.text = str(runtime_min)

    if studio:
        studio_el = ET.SubElement(root, "studio")
        studio_el.text = studio

    if country:
        country_el = ET.SubElement(root, "country")
        country_el.text = country

    if netflix_id:
        uniqueid_el = ET.SubElement(root, "uniqueid", type="netflix", default="true")
        uniqueid_el.text = str(netflix_id)

    if genres:
        for g in genres:
            if g and g.strip():
                g_el = ET.SubElement(root, "genre")
                g_el.text = g.strip()

    if tags:
        for t in tags:
            if t and t.strip():
                t_el = ET.SubElement(root, "tag")
                t_el.text = t.strip()

    if directors:
        for d in directors:
            if d and d.strip():
                d_el = ET.SubElement(root, "director")
                d_el.text = d.strip()

    if creators:
        for c in creators:
            if c and c.strip():
                c_el = ET.SubElement(root, "credits")
                c_el.text = c.strip()

    if actors:
        for a in actors:
            if a and a.strip():
                actor_el = ET.SubElement(root, "actor")
                name_el = ET.SubElement(actor_el, "name")
                name_el.text = a.strip()

    if poster_url:
        poster_el = ET.SubElement(root, "poster")
        poster_el.text = poster_url
        thumb_p = ET.SubElement(root, "thumb", aspect="poster")
        thumb_p.text = poster_url

    if logo_url:
        logo_el = ET.SubElement(root, "clearlogo")
        logo_el.text = logo_url
        thumb_l = ET.SubElement(root, "thumb", aspect="clearlogo")
        thumb_l.text = logo_url

    if fanart_url:
        fanart_el = ET.SubElement(root, "fanart")
        fanart_thumb = ET.SubElement(fanart_el, "thumb")
        fanart_thumb.text = fanart_url
        thumb_b = ET.SubElement(root, "thumb", aspect="banner")
        thumb_b.text = fanart_url

    if trailer_url:
        trailer_el = ET.SubElement(root, "trailer")
        trailer_el.text = trailer_url

    if is_tv and season_count and season_count > 0:
        season_el = ET.SubElement(root, "season")
        season_el.text = str(season_count)
        
    # Indent the XML for pretty-printing (supported in Python 3.9+)
    ET.indent(root, space="    ")
    
    # Serialize to string
    xml_str = ET.tostring(root, encoding="utf-8").decode("utf-8")
    
    # Add standard XML declaration
    declaration = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
    return declaration + xml_str

def write_nfo_file(media_item_path: str, xml_content: str, filename: str):
    """
    Writes the NFO XML content to a file.
    Creates parent directories if they do not exist.
    """
    os.makedirs(media_item_path, exist_ok=True)
    full_path = os.path.join(media_item_path, filename)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    logger.info(f"Successfully wrote NFO file to {full_path}")
