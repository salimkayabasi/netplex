import os
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger(__name__)

def generate_nfo_xml(title: str, year: int, plot: str, netflix_id: str | None = None, is_tv: bool = False) -> str:
    """
    Generates standard Plex-compatible XML metadata string for a movie or TV show.
    """
    root_tag = "tvshow" if is_tv else "movie"
    root = ET.Element(root_tag)
    
    title_el = ET.SubElement(root, "title")
    title_el.text = title
    
    year_el = ET.SubElement(root, "year")
    year_el.text = str(year)
    
    plot_el = ET.SubElement(root, "plot")
    plot_el.text = plot
    
    if netflix_id:
        uniqueid_el = ET.SubElement(root, "uniqueid", type="netflix", default="true")
        uniqueid_el.text = str(netflix_id)
        
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
