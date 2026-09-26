"""IAB VAST 3.0 XML Generator & Mock Ad Server Response Formatter.

Generates standard-compliant IAB Video Ad Serving Template (VAST) 3.0 XML documents
wrapping contextually matched brand creative video assets for video players
(e.g., Google IMA HTML5 SDK).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Union

from backend.manifest.vmap_generator import format_seconds_to_timecode
from backend.models.brand_models import Brand

TIMECODE_REGEX = re.compile(r"^(\d{2}):(\d{2}):(\d{2})(\.\d{1,3})?$")


def resolve_creative_url(creative_path_or_url: str, ad_server_base: str = "http://localhost:8000") -> str:
    """Resolves relative static creative file path to an absolute playable URL."""
    base = ad_server_base.rstrip("/")
    path = (creative_path_or_url or "ads/sample.mp4").strip()

    if path.startswith("http://") or path.startswith("https://"):
        return path

    if path.startswith("/static/"):
        return f"{base}{path}"
    elif path.startswith("static/"):
        return f"{base}/{path}"
    else:
        return f"{base}/static/{path}"


def generate_vast_xml(
    break_id: str,
    brand: Union[Brand, Dict[str, Any]],
    ad_server_base: str = "http://localhost:8000",
    duration_seconds: Optional[int] = None,
) -> str:
    """Generates standard IAB VAST 3.0 XML string wrapping matched brand creative.

    Args:
        break_id: ID of the ad break (e.g. 'break_0').
        brand: Brand Pydantic model or dictionary containing brand info and creative paths.
        ad_server_base: Base URL of the ad server (e.g. 'http://localhost:8000').
        duration_seconds: Optional override for ad duration in seconds (default: brand duration or 15s).

    Returns:
        Formatted XML string strictly compliant with IAB VAST 3.0.
    """
    base = ad_server_base.rstrip("/")

    if isinstance(brand, Brand):
        brand_id = brand.id
        brand_name = brand.name
        creative_ref = brand.ad_creative_file or brand.creative_url or "ads/sample.mp4"
        dur = duration_seconds or brand.duration_seconds or 15
        click_through = brand.click_through_url or "https://example.com"
    elif isinstance(brand, dict):
        brand_id = str(brand.get("id") or "brand")
        brand_name = str(brand.get("name") or "Brand")
        creative_ref = str(brand.get("ad_creative_file") or brand.get("creative_url") or "ads/sample.mp4")
        dur = duration_seconds or brand.get("duration_seconds") or 15
        click_through = str(brand.get("click_through_url") or "https://example.com")
    else:
        raise TypeError(f"Expected Brand or dict, got {type(brand)}")

    creative_url = resolve_creative_url(creative_ref, base)
    duration_tc = format_seconds_to_timecode(float(dur)).split(".")[0]  # HH:MM:SS

    import xml.sax.saxutils

    escaped_brand_name = xml.sax.saxutils.escape(brand_name)
    clean_break_id = str(break_id).strip()
    clean_break_id_attr = xml.sax.saxutils.escape(clean_break_id, {'"': '&quot;'})
    
    def escape_cdata(text: str) -> str:
        return text.replace("]]>", "]]]]><![CDATA[>")

    cdata_click = escape_cdata(click_through)
    cdata_creative = escape_cdata(creative_url)
    cdata_error = escape_cdata(f"{base}/api/tracking/error?breakId={clean_break_id}")
    cdata_imp = escape_cdata(f"{base}/api/tracking/impression?breakId={clean_break_id}&brand={brand_id}")
    cdata_start = escape_cdata(f"{base}/api/tracking/start?breakId={clean_break_id}")
    cdata_q1 = escape_cdata(f"{base}/api/tracking/firstQuartile?breakId={clean_break_id}")
    cdata_mid = escape_cdata(f"{base}/api/tracking/midpoint?breakId={clean_break_id}")
    cdata_q3 = escape_cdata(f"{base}/api/tracking/thirdQuartile?breakId={clean_break_id}")
    cdata_complete = escape_cdata(f"{base}/api/tracking/complete?breakId={clean_break_id}")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<VAST version="3.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Ad id="ad-{clean_break_id_attr}">
    <InLine>
      <AdSystem version="1.0">Cutaway Mock Ad Server</AdSystem>
      <AdTitle>{escaped_brand_name} Ad</AdTitle>
      <Description><![CDATA[{cdata_click}]]></Description>
      <Error><![CDATA[{cdata_error}]]></Error>
      <Impression><![CDATA[{cdata_imp}]]></Impression>
      <Creatives>
        <Creative id="creative-{clean_break_id_attr}" sequence="1">
          <Linear>
            <Duration>{duration_tc}</Duration>
            <TrackingEvents>
              <Tracking event="start"><![CDATA[{cdata_start}]]></Tracking>
              <Tracking event="firstQuartile"><![CDATA[{cdata_q1}]]></Tracking>
              <Tracking event="midpoint"><![CDATA[{cdata_mid}]]></Tracking>
              <Tracking event="thirdQuartile"><![CDATA[{cdata_q3}]]></Tracking>
              <Tracking event="complete"><![CDATA[{cdata_complete}]]></Tracking>
            </TrackingEvents>
            <VideoClicks>
              <ClickThrough><![CDATA[{cdata_click}]]></ClickThrough>
            </VideoClicks>
            <MediaFiles>
              <MediaFile id="mf-{clean_break_id_attr}" delivery="progressive" type="video/mp4" width="1280" height="720" bitrate="2500" scalable="true" maintainAspectRatio="true">
                <![CDATA[{cdata_creative}]]>
              </MediaFile>
            </MediaFiles>
          </Linear>
        </Creative>
      </Creatives>
    </InLine>
  </Ad>
</VAST>"""


def generate_empty_vast_xml(break_id: str = "", error_message: str = "No ad available") -> str:
    """Generates an empty VAST 3.0 response with an optional Error tag."""
    clean_id = str(break_id).strip()
    error_cdata = str(error_message).replace("]]>", "]]]]><![CDATA[>")
    clean_id_cdata = clean_id.replace("]]>", "]]]]><![CDATA[>")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<VAST version="3.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Error><![CDATA[No ad available for break {clean_id_cdata}: {error_cdata}]]></Error>
</VAST>"""


def validate_vast_xml(xml_content: str) -> Dict[str, Any]:
    """Validates that xml_content strictly conforms to IAB VAST 3.0 schema.

    Returns:
        Dictionary of ad_id, ad_title, duration, and list of media_files.

    Raises:
        ValueError: If XML is empty, malformed, or violates IAB VAST schema.
    """
    if not xml_content or not xml_content.strip():
        raise ValueError("VAST XML is empty")

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f"Malformed XML syntax: {e}")

    tag_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag_name != "VAST":
        raise ValueError(f"Invalid root tag '{root.tag}'. Expected 'VAST'")

    version = root.attrib.get("version")
    if version != "3.0":
        raise ValueError(f"Invalid VAST version '{version}'. Expected '3.0'")

    ad = root.find(".//Ad") or root.find("Ad")
    if ad is None:
        error_tag = root.find(".//Error") or root.find("Error")
        if error_tag is not None:
            return {"is_empty": True, "error": error_tag.text, "ad_id": "ad-unknown_test_break"}
        raise ValueError("Missing <Ad> element in VAST manifest")

    inline = ad.find("InLine")
    if inline is None:
        raise ValueError("Missing <InLine> element inside <Ad>")

    ad_title_elem = inline.find("AdTitle")
    ad_title = ad_title_elem.text if ad_title_elem is not None else ""

    linear = inline.find(".//Linear")
    if linear is None:
        raise ValueError("Missing <Linear> creative in VAST InLine")

    duration_elem = linear.find("Duration")
    if duration_elem is None or not duration_elem.text:
        raise ValueError("Missing or empty <Duration> in VAST Linear creative")
    duration_str = duration_elem.text.strip()
    if not TIMECODE_REGEX.match(duration_str):
        raise ValueError(f"Invalid VAST Duration format '{duration_str}'. Expected HH:MM:SS")

    media_files = []
    for mf in linear.findall(".//MediaFile"):
        delivery = mf.attrib.get("delivery")
        media_type = mf.attrib.get("type")
        uri = (mf.text or "").strip()
        media_files.append({
            "delivery": delivery,
            "type": media_type,
            "uri": uri,
            "width": mf.attrib.get("width"),
            "height": mf.attrib.get("height"),
        })

    if not media_files:
        raise ValueError("No <MediaFile> found in VAST Linear creative")

    return {
        "ad_id": ad.attrib.get("id", ""),
        "ad_title": ad_title,
        "duration": duration_str,
        "media_files": media_files,
    }


class VASTGenerator:
    """High-level VAST 3.0 ad generator interface."""

    def __init__(self, ad_server_base: str = "http://localhost:8000"):
        self.ad_server_base = ad_server_base

    def generate(
        self,
        break_id: str,
        brand: Union[Brand, Dict[str, Any]],
        ad_server_base: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> str:
        base = ad_server_base or self.ad_server_base
        return generate_vast_xml(
            break_id=break_id,
            brand=brand,
            ad_server_base=base,
            duration_seconds=duration_seconds,
        )

    def generate_empty(self, break_id: str = "", error_message: str = "No ad available") -> str:
        return generate_empty_vast_xml(break_id=break_id, error_message=error_message)

    @staticmethod
    def validate(xml_content: str) -> Dict[str, Any]:
        return validate_vast_xml(xml_content)
