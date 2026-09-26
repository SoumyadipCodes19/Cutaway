"""Unit and Integration Tests for Milestone 3: Manifests, Ad Server, and FastAPI Application.

Covers:
1. IAB VMAP 1.0.1 XML Generation & Validation (F11)
2. IAB VAST 3.0 XML Generation & Mock Ad Server (F12)
3. Parallel debug.json Export & Schema Validation (F13)
4. Static Media Creatives Serving (/static/ads/ & /static/sample_videos/)
5. FastAPI Server Endpoints:
   - POST /api/pipeline/run (JSON & multipart file upload)
   - GET  /api/pipeline/status/{sessionId}
   - GET  /api/pipeline/stream/{sessionId} (Server-Sent Events)
   - GET  /vmap/{sessionId} & /vmap?sessionId=...
   - GET  /vast?breakId=... & /vast/{breakId} (CORS headers)
   - GET  /api/debug/{sessionId} & /api/debug?sessionId=...
   - GET  /api/brands & POST /api/brands (dynamic 9th brand test)
   - GET  /api/presets (demo presets)
   - GET  /api/video/{sessionId}
   - GET  /api/tracking/{event}
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from backend.manifest.debug_exporter import (
    build_debug_json,
    export_debug_json,
    save_debug_json,
    validate_debug_manifest,
)
from backend.manifest.vast_generator import (
    VASTGenerator,
    generate_empty_vast_xml,
    generate_vast_xml,
    resolve_creative_url,
    validate_vast_xml,
)
from backend.manifest.vmap_generator import (
    VMAPGenerator,
    format_seconds_to_timecode,
    generate_vmap_xml,
    validate_vmap_xml,
)
from backend.models.brand_models import Brand, BrandEvaluation, BrandMatchResult, SceneUnderstanding
from backend.models.pipeline_models import (
    CandidateBreak,
    PipelineConfig,
    PipelineResult,
    SceneBoundary,
    SpeechInterval,
    VideoMetadata,
)
from backend.server.app import app, brand_matcher, session_store
from backend.server.media_generator import (
    PRESET_VIDEOS_DIR,
    ensure_demo_presets,
    ensure_static_ads,
)


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    ensure_static_ads()
    ensure_demo_presets()
    return TestClient(app)


# ============================================================================
# 1. VMAP 1.0.1 Generator Tests (F11)
# ============================================================================

def test_vmap_root_and_namespace():
    """Validates root <vmap:VMAP> tag and IAB namespace."""
    breaks = [{"break_id": "b1", "cut_time": 90.0}]
    xml = generate_vmap_xml(breaks)
    parsed = validate_vmap_xml(xml)
    assert parsed["version"] in ("1.0", "1.0.1")
    assert parsed["break_count"] == 1


def test_vmap_timeoffset_formatting():
    """Validates timeOffset formatting adheres to HH:MM:SS.mmm."""
    assert format_seconds_to_timecode(0.0) == "00:00:00.000"
    assert format_seconds_to_timecode(125.45) == "00:02:05.450"
    assert format_seconds_to_timecode(3665.123) == "01:01:05.123"

    breaks = [{"break_id": "b1", "cut_time": 125.45}]
    xml = generate_vmap_xml(breaks)
    parsed = validate_vmap_xml(xml)
    assert parsed["ad_breaks"][0]["time_offset"] == "00:02:05.450"


def test_vmap_break_count_and_ids():
    """Validates that each scheduled break generates one <vmap:AdBreak> with matching breakId."""
    breaks = [
        {"break_id": "break_10", "cut_time": 60.0},
        {"break_id": "break_20", "cut_time": 180.0},
        {"break_id": "break_30", "cut_time": 300.0},
    ]
    xml = generate_vmap_xml(breaks)
    parsed = validate_vmap_xml(xml)
    assert parsed["break_count"] == 3
    assert [b["break_id"] for b in parsed["ad_breaks"]] == ["break_10", "break_20", "break_30"]


def test_vmap_ad_tag_uri_vast3_template():
    """Validates AdTagURI points to mock ad server and sets templateType='vast3'."""
    breaks = [{"break_id": "break_alpha", "cut_time": 75.0}]
    xml = generate_vmap_xml(breaks, ad_server_base_url="http://localhost:8000/vast")
    parsed = validate_vmap_xml(xml)
    ad_tag = parsed["ad_breaks"][0]["ad_tag_uri"]
    assert "http://localhost:8000/vast?breakId=break_alpha" in ad_tag


def test_vmap_empty_breaks_produces_valid_vmap():
    """Validates that empty list of scheduled breaks produces valid empty VMAP."""
    xml = generate_vmap_xml([])
    parsed = validate_vmap_xml(xml)
    assert parsed["break_count"] == 0
    assert parsed["version"] == "1.0"


def test_vmap_excludes_rejected_and_dropped_breaks():
    """Validates that candidate breaks marked as rejected or dropped are not emitted in VMAP."""
    breaks = [
        {"break_id": "b1", "cut_time": 60.0, "status": "SELECTED"},
        {"break_id": "b2", "cut_time": 120.0, "status": "REJECTED_VAD"},
        {"break_id": "b3", "cut_time": 180.0, "status": "REJECTED_PACING"},
        {"break_id": "b4", "cut_time": 240.0, "status": "DROPPED_ALL_BRANDS_GATED"},
        {"break_id": "b5", "cut_time": 300.0, "is_dropped": True},
    ]
    xml = generate_vmap_xml(breaks)
    parsed = validate_vmap_xml(xml)
    assert parsed["break_count"] == 1
    assert parsed["ad_breaks"][0]["break_id"] == "b1"


def test_vmap_class_interface():
    """Validates VMAPGenerator helper class."""
    gen = VMAPGenerator(ad_server_base_url="http://localhost:8000/vast")
    xml = gen.generate([{"break_id": "b_class", "cut_time": 45.0}])
    parsed = gen.validate(xml)
    assert parsed["break_count"] == 1


# ============================================================================
# 2. VAST 3.0 Generator Tests (F12)
# ============================================================================

def test_vast_version_3_root_and_inline():
    """Validates VAST XML has root <VAST version='3.0'> and contains InLine creative."""
    brand = {
        "id": "zenith_motors",
        "name": "Zenith Motors",
        "ad_creative_file": "ads/zenith_motors.mp4",
        "duration_seconds": 15,
        "click_through_url": "https://zenithmotors.example.com",
    }
    xml = generate_vast_xml(break_id="break_1", brand=brand)
    parsed = validate_vast_xml(xml)
    assert parsed["ad_id"] == "ad-break_1"
    assert "Zenith Motors" in parsed["ad_title"]
    assert parsed["duration"] == "00:00:15"


def test_vast_progressive_mp4_mediafile():
    """Validates MediaFile has delivery='progressive', type='video/mp4', and valid URL."""
    brand = {
        "id": "aura_sparkling_water",
        "name": "Aura Sparkling Water",
        "ad_creative_file": "ads/aura_sparkling.mp4",
        "duration_seconds": 15,
    }
    xml = generate_vast_xml(break_id="break_2", brand=brand, ad_server_base="http://localhost:8000")
    parsed = validate_vast_xml(xml)
    assert len(parsed["media_files"]) >= 1
    mf = parsed["media_files"][0]
    assert mf["delivery"] == "progressive"
    assert mf["type"] == "video/mp4"
    assert "http://localhost:8000/static/ads/aura_sparkling.mp4" in mf["uri"]


def test_vast_tracking_events_and_clickthrough():
    """Validates VAST tracking events (start, firstQuartile, midpoint, thirdQuartile, complete)."""
    brand = {
        "id": "nova_cloud",
        "name": "Nova Cloud Systems",
        "ad_creative_file": "ads/nova_cloud.mp4",
        "duration_seconds": 15,
        "click_through_url": "https://novacloud.example.com",
    }
    xml = generate_vast_xml(break_id="break_3", brand=brand)
    assert "<ClickThrough><![CDATA[https://novacloud.example.com]]></ClickThrough>" in xml
    for ev in ["start", "firstQuartile", "midpoint", "thirdQuartile", "complete"]:
        assert f'event="{ev}"' in xml
    assert "<Impression>" in xml
    assert "<Error>" in xml


def test_vast_resolve_creative_url_relative_and_absolute():
    """Validates resolve_creative_url handles relative, prefixed, and absolute URLs."""
    assert (
        resolve_creative_url("ads/apex_athletics.mp4", "http://localhost:8000")
        == "http://localhost:8000/static/ads/apex_athletics.mp4"
    )
    assert (
        resolve_creative_url("/static/ads/apex_athletics.mp4", "http://localhost:8000")
        == "http://localhost:8000/static/ads/apex_athletics.mp4"
    )
    assert (
        resolve_creative_url("https://cdn.example.com/ad.mp4", "http://localhost:8000")
        == "https://cdn.example.com/ad.mp4"
    )


def test_vast_empty_vast_generation():
    """Validates empty VAST 3.0 response with Error element."""
    xml = generate_empty_vast_xml("b_empty", "No brand eligible")
    assert '<VAST version="3.0"' in xml
    assert "<Error>" in xml
    assert "No brand eligible" in xml


def test_vast_class_interface():
    """Validates VASTGenerator helper class."""
    gen = VASTGenerator(ad_server_base="http://localhost:8000")
    brand = Brand(
        id="haven_financial",
        name="Haven Wealth & Trust",
        category="Banking",
        creative_url="ads/haven_financial.mp4",
        duration_seconds=15,
    )
    xml = gen.generate(break_id="b_class", brand=brand)
    parsed = gen.validate(xml)
    assert "Haven Wealth & Trust" in parsed["ad_title"]


# ============================================================================
# 3. Debug Manifest Exporter Tests (F13)
# ============================================================================

def test_debug_json_required_keys_and_validation():
    """Validates debug.json contains all required schema keys."""
    meta = {"duration": 60.0, "fps": 30.0, "total_frames": 1800, "width": 1280, "height": 720}
    debug_dict = build_debug_json(
        session_id="session_test_1",
        video_meta=meta,
        scenes=[{"scene_id": 0, "start_time": 0.0, "end_time": 30.0}],
        speech_intervals=[(2.0, 5.0), (10.0, 15.0)],
        candidate_breaks=[{"break_id": "b1", "cut_time": 30.0, "vad_safe": True, "pacing_valid": True, "status": "SELECTED"}],
        final_breaks=[{"break_id": "b1", "cut_time": 30.0, "matched_brand": {"name": "Apex Athletics"}, "brand_score": 75.0}],
    )
    assert validate_debug_manifest(debug_dict) is True
    assert debug_dict["session_id"] == "session_test_1"
    assert len(debug_dict["scenes"]) == 1
    assert len(debug_dict["speech_intervals"]) == 2
    assert len(debug_dict["final_breaks"]) == 1


def test_debug_json_rejection_reasons_preserved():
    """Validates candidate break rejection reasons are preserved."""
    candidates = [
        {"break_id": "b_rej_vad", "cut_time": 10.0, "vad_safe": False, "pacing_valid": False, "status": "REJECTED_VAD", "rejection_reason": "Speech overlap"},
        {"break_id": "b_rej_pace", "cut_time": 20.0, "vad_safe": True, "pacing_valid": False, "status": "REJECTED_PACING", "rejection_reason": "Min gap violated"},
    ]
    debug_dict = build_debug_json("s_rej", {"duration": 60.0, "fps": 30.0, "total_frames": 1800}, [], [], candidates, [])
    assert debug_dict["candidate_breaks"][0]["rejection_reason"] == "Speech overlap"
    assert debug_dict["candidate_breaks"][1]["rejection_reason"] == "Min gap violated"


def test_debug_json_save_to_disk(tmp_path: Path):
    """Validates save_debug_json serializes to file properly."""
    debug_dict = build_debug_json("s_disk", {"duration": 30.0, "fps": 30.0, "total_frames": 900}, [], [], [], [])
    target = tmp_path / "debug.json"
    saved_path = save_debug_json(debug_dict, target)
    assert os.path.exists(saved_path)
    with open(saved_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["session_id"] == "s_disk"


# ============================================================================
# 4. Static Media Creatives Serving Tests
# ============================================================================

def test_static_ads_serving(client: TestClient):
    """Validates that mock ad MP4 files are served over HTTP with 200 status."""
    res = client.get("/static/ads/apex_athletics.mp4")
    assert res.status_code == 200
    assert res.headers["content-type"] in ("video/mp4", "application/octet-stream")
    assert len(res.content) > 1000


def test_static_sample_videos_serving(client: TestClient):
    """Validates that sample demo preset videos are served over HTTP with 200 status."""
    res = client.get("/static/sample_videos/tech_review.mp4")
    assert res.status_code == 200
    assert len(res.content) > 1000


# ============================================================================
# 5. FastAPI Endpoints Integration Tests
# ============================================================================

def test_api_presets_endpoint(client: TestClient):
    """Validates GET /api/presets returns 4 demo presets with descriptions."""
    res = client.get("/api/presets")
    assert res.status_code == 200
    presets = res.json()
    assert len(presets) >= 4
    preset_ids = {p["id"] for p in presets}
    assert "tech_review" in preset_ids
    assert "sports_adventure" in preset_ids
    assert "gourmet_kitchen" in preset_ids
    assert "action_thriller" in preset_ids


def test_api_brands_get_and_post_9th_brand(client: TestClient):
    """AC-What: Validates GET /api/brands (8 brands) and dynamic 9th brand addition via POST."""
    # Step 1: GET /api/brands
    res = client.get("/api/brands")
    assert res.status_code == 200
    brands = res.json()
    assert len(brands) >= 8
    assert res.headers.get("access-control-allow-origin") == "*"

    # Step 2: POST /api/brands (inject 9th unseen brand)
    unseen_brand = {
        "id": "cyber_shield_defense",
        "name": "CyberShield Defense",
        "category": "Enterprise Cybersecurity",
        "positive_contexts": ["technology", "cybersecurity", "software", "office"],
        "negative_contexts": ["data_breach", "server_crash", "crime_illegal", "death_injury"],
        "ad_creative_file": "ads/cyber_shield.mp4",
        "duration_seconds": 15,
        "click_through_url": "https://cybershield.example.com",
    }
    post_res = client.post("/api/brands", json=unseen_brand)
    assert post_res.status_code == 201
    added = post_res.json()
    assert added["id"] == "cyber_shield_defense"

    # Step 3: Verify 9th brand is in catalogue
    get_res2 = client.get("/api/brands")
    brands2 = get_res2.json()
    assert any(b["id"] == "cyber_shield_defense" for b in brands2)


def test_api_pipeline_run_with_preset(client: TestClient):
    """End-to-end: POST /api/pipeline/run with preset_id, status check, VMAP, VAST, debug.json."""
    # 1. Run pipeline
    payload = {
        "preset_id": "tech_review",
        "safety_window_seconds": 0.5,
        "min_start_buffer_seconds": 0.5,
        "min_end_buffer_seconds": 0.5,
        "min_gap_seconds": 1.0,
        "max_breaks_per_hour": 10.0,
        "ad_load_pct": 20.0,
    }
    run_res = client.post("/api/pipeline/run", json=payload)
    assert run_res.status_code == 200
    run_data = run_res.json()
    session_id = run_data["session_id"]
    assert session_id.startswith("run_")
    assert run_data["status"] in ("PENDING", "PROCESSING")
    assert run_data["vmap_url"] == f"/vmap/{session_id}"
    assert run_data["debug_url"] == f"/api/debug/{session_id}"

    # Wait for completion
    import time
    start_time = time.time()
    while time.time() - start_time < 30:
        status_res = client.get(f"/api/pipeline/status/{session_id}")
        assert status_res.status_code == 200
        st_data = status_res.json()
        if st_data["status"] == "COMPLETED":
            break
        time.sleep(0.5)
    else:
        pytest.fail("Pipeline did not complete in time")

    # 2. Check status
    assert st_data["status"] == "COMPLETED"
    assert st_data["progress_percent"] == 100
    assert len(st_data["stages_completed"]) >= 8

    # 3. Check VMAP manifest (path & query parameter)
    vmap_res = client.get(f"/vmap/{session_id}")
    assert vmap_res.status_code == 200
    assert "application/xml" in vmap_res.headers["content-type"]
    assert vmap_res.headers.get("access-control-allow-origin") == "*"
    vmap_xml = vmap_res.text
    parsed_vmap = validate_vmap_xml(vmap_xml)
    assert parsed_vmap["version"] in ("1.0", "1.0.1")

    # Also test /vmap?sessionId=...
    vmap_res_query = client.get(f"/vmap?sessionId={session_id}")
    assert vmap_res_query.status_code == 200
    assert vmap_res_query.text == vmap_xml

    # 4. Check debug.json manifest (path & query parameter)
    debug_res = client.get(f"/api/debug/{session_id}")
    assert debug_res.status_code == 200
    debug_data = debug_res.json()
    assert validate_debug_manifest(debug_data) is True
    assert debug_data["session_id"] == session_id

    # Also test /api/debug?sessionId=...
    debug_res_query = client.get(f"/api/debug?sessionId={session_id}")
    assert debug_res_query.status_code == 200
    assert debug_res_query.json() == debug_data

    # 5. Check video streaming endpoint
    video_res = client.get(f"/api/video/{session_id}")
    assert video_res.status_code == 200
    assert "video/mp4" in video_res.headers["content-type"]

    # 6. Check VAST ad server endpoint for scheduled breaks
    if parsed_vmap["break_count"] > 0:
        first_break_id = parsed_vmap["ad_breaks"][0]["break_id"]
        vast_res = client.get(f"/vast?breakId={first_break_id}")
        assert vast_res.status_code == 200
        assert "application/xml" in vast_res.headers["content-type"]
        assert vast_res.headers.get("access-control-allow-origin") == "*"
        vast_xml = vast_res.text
        parsed_vast = validate_vast_xml(vast_xml)
        assert parsed_vast["ad_id"] == f"ad-{first_break_id}"


def test_api_pipeline_run_with_file_upload(client: TestClient):
    """Validates POST /api/pipeline/run with multipart video file upload."""
    sample_video_path = PRESET_VIDEOS_DIR / "sports_adventure.mp4"
    with open(sample_video_path, "rb") as f:
        video_bytes = f.read()

    files = {"file": ("uploaded_sports.mp4", io.BytesIO(video_bytes), "video/mp4")}
    data = {
        "safety_window_seconds": "0.5",
        "min_start_buffer_seconds": "0.5",
        "min_end_buffer_seconds": "0.5",
        "min_gap_seconds": "1.0",
    }
    res = client.post("/api/pipeline/run", files=files, data=data)
    assert res.status_code == 200
    session_id = res.json()["session_id"]
    assert res.json()["status"] in ("PENDING", "PROCESSING")

    import time
    start_time = time.time()
    while time.time() - start_time < 30:
        st_res = client.get(f"/api/pipeline/status/{session_id}")
        if st_res.json()["status"] == "COMPLETED":
            break
        time.sleep(0.5)
    else:
        pytest.fail("Pipeline did not complete in time")

    # Verify debug.json is readable for uploaded session
    dbg_res = client.get(f"/api/debug/{session_id}")
    assert dbg_res.status_code == 200
    assert dbg_res.json()["session_id"] == session_id


def test_api_pipeline_sse_stream(client: TestClient):
    """Validates GET /api/pipeline/stream/{sessionId} returns valid SSE event stream."""
    # First run a session
    run_res = client.post("/api/pipeline/run", json={"preset_id": "gourmet_kitchen"})
    session_id = run_res.json()["session_id"]

    # Stream events
    stream_res = client.get(f"/api/pipeline/stream/{session_id}")
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.headers["content-type"]
    assert stream_res.headers.get("access-control-allow-origin") == "*"

    content = stream_res.text
    assert "data: {" in content
    # Parse at least one event from stream
    lines = [line for line in content.split("\n") if line.startswith("data: ")]
    assert len(lines) >= 8
    first_event = json.loads(lines[0][6:])
    assert first_event["session_id"] == session_id
    assert "stage" in first_event


def test_api_vast_fallback_and_cors(client: TestClient):
    """Validates GET /vast returns valid VAST 3.0 and CORS headers even for unknown breakId."""
    res = client.get("/vast?breakId=unknown_test_break")
    assert res.status_code == 200
    assert "application/xml" in res.headers["content-type"]
    assert res.headers.get("access-control-allow-origin") == "*"
    vast_xml = res.text
    parsed = validate_vast_xml(vast_xml)
    assert parsed["ad_id"] == "ad-unknown_test_break"


def test_api_tracking_beacon(client: TestClient):
    """Validates GET /api/tracking/{event} returns 204 No Content with CORS."""
    res = client.get("/api/tracking/start?breakId=break_1")
    assert res.status_code == 204
    assert res.headers.get("access-control-allow-origin") == "*"
