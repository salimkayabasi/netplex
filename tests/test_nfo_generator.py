import os
import xml.etree.ElementTree as ET
import pytest
from src.metadata.nfo_generator import generate_nfo_xml, write_nfo_file

def test_generate_nfo_xml_movie():
    xml_str = generate_nfo_xml(
        title="Inside Out 2",
        year=2024,
        plot="Follow-up story showing Riley entering her teenage years.",
        netflix_id="81234567",
        is_tv=False
    )
    assert '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>' in xml_str
    assert "<movie>" in xml_str
    assert "</movie>" in xml_str
    
    # Parse back to verify well-formed XML
    content_without_declaration = xml_str.replace('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', '').strip()
    root = ET.fromstring(content_without_declaration)
    assert root.tag == "movie"
    assert root.find("title").text == "Inside Out 2"
    assert root.find("year").text == "2024"
    assert root.find("plot").text == "Follow-up story showing Riley entering her teenage years."
    
    uniqueid = root.find("uniqueid")
    assert uniqueid is not None
    assert uniqueid.attrib.get("type") == "netflix"
    assert uniqueid.attrib.get("default") == "true"
    assert uniqueid.text == "81234567"

def test_generate_nfo_xml_tvshow():
    xml_str = generate_nfo_xml(
        title="Stranger Things",
        year=2016,
        plot="When a young boy vanishes, a small town uncovers a mystery.",
        netflix_id="80057281",
        is_tv=True
    )
    assert "<tvshow>" in xml_str
    assert "</tvshow>" in xml_str
    
    content_without_declaration = xml_str.replace('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', '').strip()
    root = ET.fromstring(content_without_declaration)
    assert root.tag == "tvshow"
    assert root.find("title").text == "Stranger Things"
    assert root.find("year").text == "2016"

def test_generate_nfo_xml_special_characters():
    xml_str = generate_nfo_xml(
        title="Tom & Jerry <Movie>",
        year=2021,
        plot="A chaotic battle between Tom & Jerry > all else.",
        is_tv=False
    )
    assert "Tom &amp; Jerry &lt;Movie&gt;" in xml_str
    assert "Tom &amp; Jerry &gt; all else." in xml_str
    
    # Verify XML can be parsed back with unescaped characters preserved
    content_without_declaration = xml_str.replace('<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>', '').strip()
    root = ET.fromstring(content_without_declaration)
    assert root.find("title").text == "Tom & Jerry <Movie>"
    assert root.find("plot").text == "A chaotic battle between Tom & Jerry > all else."

def test_write_nfo_file(tmp_path):
    target_dir = tmp_path / "movies" / "Inside Out 2 (2024)"
    xml_content = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n<movie>\n</movie>'
    
    write_nfo_file(str(target_dir), xml_content, "movie.nfo")
    
    nfo_path = target_dir / "movie.nfo"
    assert nfo_path.exists()
    assert nfo_path.read_text(encoding="utf-8") == xml_content
