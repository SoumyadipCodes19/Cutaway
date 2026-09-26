"""IAB VMAP 1.0.1 XML Manifest Generator.

Generates valid IAB Video Multiple Ad Playlist (VMAP) 1.0.1 XML manifests
for commercial ad breaks identified by the Cutaway pipeline.
Each approved ad break specifies:
- timeOffset in HH:MM:SS.mmm format
- breakType="linear"
- breakId uniquely referencing the scheduled candidate cut
- AdTagURI pointing to the mock VAST 3.0 ad server endpoint
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Union

from backend.models.pipeline_models import CandidateBreak

VMAP_NS = {"vmap": "http://www.iab.net/videosuite/vmap"}
TIMECODE_REGEX = re.compile(r"^(\d{2}):(\d{2}):(\d{2})(\.\d{1,3})?$")


def format_seconds_to_timecode(seconds: float) -> str:
    """Formats float seconds into standard HH:MM:SS.mmm timecode format for VMAP."""
    if seconds < 0:
        seconds = 0.0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis = 0
    return f"{hrs:02d}:{mins:02d}:{secs:02d}.{millis:03d}"


def build_vast_tag_url(ad_server_base_url: str, break_id: str) -> str:
    """Constructs the VAST ad tag URI with query parameter breakId."""
    clean_base = (ad_server_base_url or "http://localhost:8000/vast").strip()
    if "?" in clean_base:
        return f"{clean_base}&breakId={break_id}"
    elif clean_base.endswith("/vast"):
        return f"{clean_base}?breakId={break_id}"
    else:
        return f"{clean_base.rstrip('/')}/vast?breakId={break_id}"


def generate_vmap_xml(
    scheduled_breaks: List[Union[CandidateBreak, Dict[str, Any], Any]],
    ad_server_base_url: str = "http://localhost:8000/vast",
    version: str = "1.0",
) -> str:
    """Generates a valid IAB VMAP 1.0.1 XML document from a list of scheduled breaks.

    Args:
        scheduled_breaks: List of CandidateBreak models or dicts with break_id and cut_time.
        ad_server_base_url: Base URL for the VAST mock ad server (default: http://localhost:8000/vast).
        version: VMAP specification version (default: '1.0').

    Returns:
        Formatted XML string conforming strictly to IAB VMAP 1.0 / 1.0.1.
    """
    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<vmap:VMAP xmlns:vmap="http://www.iab.net/videosuite/vmap" version="{version}">',
    ]

    for item in scheduled_breaks:
        # Extract attributes from CandidateBreak or dict
        if isinstance(item, dict):
            break_id = str(item.get("break_id") or "")
            cut_time_raw = item.get("cut_time")
            status = item.get("status")
            is_dropped = item.get("is_dropped", False)
            time_offset_raw = item.get("timeOffset") or item.get("time_offset")
        else:
            break_id = str(getattr(item, "break_id", ""))
            cut_time_raw = getattr(item, "cut_time", None)
            status = getattr(item, "status", None)
            is_dropped = getattr(item, "is_dropped", False)
            time_offset_raw = getattr(item, "time_offset", None) or getattr(item, "timeOffset", None)

        # Skip explicit rejections if status indicates dropped
        if is_dropped or status in ("REJECTED_VAD", "REJECTED_PACING", "DROPPED_ALL_BRANDS_GATED", "DROPPED"):
            continue

        if not break_id:
            continue

        # Format time offset
        if time_offset_raw and isinstance(time_offset_raw, str) and (
            time_offset_raw in ("start", "end") or TIMECODE_REGEX.match(time_offset_raw)
        ):
            timecode = time_offset_raw
        elif cut_time_raw is not None:
            timecode = format_seconds_to_timecode(float(cut_time_raw))
        else:
            timecode = "00:00:00.000"

        vast_url = build_vast_tag_url(ad_server_base_url, break_id)
        
        import xml.sax.saxutils
        break_id_attr = xml.sax.saxutils.escape(break_id, {'"': '&quot;'})
        vast_url_cdata = vast_url.replace("]]>", "]]]]><![CDATA[>")

        lines.append(f'  <vmap:AdBreak timeOffset="{timecode}" breakType="linear" breakId="{break_id_attr}">')
        lines.append(f'    <vmap:AdSource id="ad-source-{break_id_attr}" allowMultipleAds="false" followRedirects="true">')
        lines.append('      <vmap:AdTagURI templateType="vast3">')
        lines.append(f'        <![CDATA[{vast_url_cdata}]]>')
        lines.append('      </vmap:AdTagURI>')
        lines.append('    </vmap:AdSource>')
        lines.append('  </vmap:AdBreak>')

    lines.append('</vmap:VMAP>')
    return "\n".join(lines)


def validate_vmap_xml(xml_content: str) -> Dict[str, Any]:
    """Validates that xml_content strictly conforms to IAB VMAP 1.0 / 1.0.1 schema.

    Returns:
        Dictionary detailing version, break_count, and parsed ad_breaks list.

    Raises:
        ValueError: If XML is empty, malformed, or violates IAB VMAP schema.
    """
    if not xml_content or not xml_content.strip():
        raise ValueError("VMAP XML is empty")

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f"Malformed XML syntax: {e}")

    # Check root tag and namespace
    if root.tag != f"{{{VMAP_NS['vmap']}}}VMAP":
        raise ValueError(f"Invalid root tag: {root.tag}. Expected {{{VMAP_NS['vmap']}}}VMAP")

    version = root.attrib.get("version")
    if version not in ("1.0", "1.0.1"):
        raise ValueError(f"Invalid VMAP version: {version}. Expected '1.0' or '1.0.1'")

    ad_breaks = []
    for elem in root.findall("vmap:AdBreak", VMAP_NS):
        break_id = elem.attrib.get("breakId")
        if not break_id:
            raise ValueError("Missing breakId attribute on vmap:AdBreak")

        time_offset = elem.attrib.get("timeOffset")
        if not time_offset:
            raise ValueError(f"Missing timeOffset attribute on vmap:AdBreak {break_id}")

        if time_offset not in ("start", "end") and not TIMECODE_REGEX.match(time_offset):
            raise ValueError(
                f"Invalid timeOffset format '{time_offset}' in break {break_id}. Expected HH:MM:SS.mmm or start/end"
            )

        break_type = elem.attrib.get("breakType")
        if break_type != "linear":
            raise ValueError(f"Invalid breakType '{break_type}' in break {break_id}. Expected 'linear'")

        ad_source = elem.find("vmap:AdSource", VMAP_NS)
        if ad_source is None:
            raise ValueError(f"Missing vmap:AdSource in break {break_id}")

        ad_tag_uri = ad_source.find("vmap:AdTagURI", VMAP_NS)
        if ad_tag_uri is None:
            raise ValueError(f"Missing vmap:AdTagURI in break {break_id}")

        template_type = ad_tag_uri.attrib.get("templateType")
        if template_type not in ("vast3", "vast2", "vast1"):
            raise ValueError(f"Invalid templateType '{template_type}'. Expected 'vast3'")

        uri_text = (ad_tag_uri.text or "").strip()
        if not uri_text:
            raise ValueError(f"Empty AdTagURI in break {break_id}")

        ad_breaks.append({
            "break_id": break_id,
            "time_offset": time_offset,
            "break_type": break_type,
            "ad_tag_uri": uri_text,
        })

    return {
        "version": version,
        "break_count": len(ad_breaks),
        "ad_breaks": ad_breaks,
    }


class VMAPGenerator:
    """High-level VMAP 1.0.1 generator interface."""

    def __init__(self, ad_server_base_url: str = "http://localhost:8000/vast"):
        self.ad_server_base_url = ad_server_base_url

    def generate(
        self,
        scheduled_breaks: List[Union[CandidateBreak, Dict[str, Any], Any]],
        ad_server_base_url: Optional[str] = None,
    ) -> str:
        url = ad_server_base_url or self.ad_server_base_url
        return generate_vmap_xml(scheduled_breaks, ad_server_base_url=url)

    @staticmethod
    def validate(xml_content: str) -> Dict[str, Any]:
        return validate_vmap_xml(xml_content)
