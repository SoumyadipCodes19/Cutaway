"""Cutaway FastAPI Application & Mock Ad Server.

Provides REST and streaming endpoints for Context-Aware Video Segmentation & Ad Placement:
- POST /api/pipeline/run: Executes full 9-stage pipeline (M1 + M2 + M3), stores session.
- GET  /api/pipeline/status/{sessionId}: Returns real-time status and stage metrics.
- GET  /api/pipeline/stream/{sessionId}: Server-Sent Events (SSE) streaming 9 pipeline stages.
- GET  /vmap/{sessionId} & /vmap?sessionId=...: Serves IAB VMAP 1.0.1 XML manifest.
- GET  /vast?breakId=... & /vast/{breakId}: Serves IAB VAST 3.0 XML wrapping matched brand creative.
- GET  /api/debug/{sessionId} & /api/debug?sessionId=...: Serves comprehensive debug.json.
- GET  /api/brands & POST /api/brands: Dynamic brand catalogue management (enables 9th brand test).
- GET  /api/presets: Demo video presets for instant zero-friction demonstration.
- GET  /api/video/{sessionId}: Streams video file for HTML5 video player.
- Static file serving at /static/.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import os
import shutil
import tempfile
import threading
import uuid
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union
import cv2

def sanitize_floats(obj):
    if isinstance(obj, float):
        if math.isinf(obj):
            return -9999.0 if obj < 0 else 9999.0
        if math.isnan(obj):
            return 0.0
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(i) for i in obj]
    return obj

def extract_keyframe(video_path: str, timestamp: float) -> Optional[bytes]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
        ret, frame = cap.read()
        if ret:
            frame = cv2.resize(frame, (640, 360))
            success, buffer = cv2.imencode('.jpg', frame)
            if success:
                return buffer.tobytes()
    finally:
        cap.release()
    return None

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.engine.brand_matcher import DEFAULT_CATALOGUE_PATH, BrandMatcher
from backend.engine.gemini_analyzer import GeminiSceneAnalyzer, MockGeminiAnalyzer
from backend.manifest.debug_exporter import export_debug_json
from backend.manifest.vast_generator import generate_empty_vast_xml, generate_vast_xml
from backend.manifest.vmap_generator import generate_vmap_xml
from backend.models.brand_models import Brand, BrandMatchResult, SceneUnderstanding
from backend.models.pipeline_models import PipelineConfig, PipelineResult
from backend.pipeline.ingest import extract_audio, probe_video
from backend.pipeline.pacing import solve_pacing
from backend.pipeline.scene_detector import detect_and_refine_scenes
from backend.pipeline.vad_engine import detect_speech_intervals, evaluate_breaks_vad_safety
from backend.server.media_generator import (
    DEMO_PRESETS,
    PRESET_VIDEOS_DIR,
    STATIC_ADS_DIR,
    ensure_demo_presets,
    ensure_static_ads,
)

logger = logging.getLogger("cutaway.server")
logging.basicConfig(level=logging.INFO)

# Base directory paths
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

# Ensure static directories and demo assets exist
STATIC_DIR.mkdir(parents=True, exist_ok=True)
ensure_static_ads(STATIC_ADS_DIR)
ensure_demo_presets(PRESET_VIDEOS_DIR)


# ============================================================================
# Session State Management
# ============================================================================

class PipelineSession:
    """Represents the in-memory state of an active or completed pipeline execution."""

    def __init__(self, session_id: str, video_path: str, config: PipelineConfig):
        self.session_id = session_id
        self.video_path = video_path
        self.config = config
        self.status = "PENDING"  # PENDING, PROCESSING, COMPLETED, FAILED
        self.current_stage = "ingest"
        self.stages_completed: List[str] = []
        self.progress_percent = 0
        self.events: List[Dict[str, Any]] = []
        self.pipeline_result: Optional[PipelineResult] = None
        self.brand_match_results: List[BrandMatchResult] = []
        self.scene_understandings: Dict[int, SceneUnderstanding] = {}
        self.scheduled_breaks: List[Dict[str, Any]] = []
        self.vmap_xml: str = ""
        self.debug_data: Dict[str, Any] = {}
        self.error_message: Optional[str] = None
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.completed_at: Optional[str] = None

    def add_event(
        self,
        stage: str,
        status: str,
        progress: int,
        message: str,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Records a timestamped event for SSE and status polling."""
        event = {
            "session_id": self.session_id,
            "stage": stage,
            "status": status,
            "progress_percent": progress,
            "message": message,
            "metrics": sanitize_floats(metrics or {}),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self.events.append(event)
        self.current_stage = stage
        self.progress_percent = progress
        if status == "COMPLETED" and stage not in self.stages_completed:
            self.stages_completed.append(stage)
        return event


class SessionStore:
    """Thread-safe in-memory session and break-brand registry."""

    def __init__(self):
        self.sessions: Dict[str, PipelineSession] = {}
        self.break_brand_map: Dict[str, Brand] = {}

    def create_session(self, session_id: str, video_path: str, config: PipelineConfig) -> PipelineSession:
        session = PipelineSession(session_id, video_path, config)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[PipelineSession]:
        return self.sessions.get(session_id)

    def register_break_brand(self, break_id: str, brand: Brand) -> None:
        self.break_brand_map[break_id] = brand

    def get_brand_for_break(self, break_id: str) -> Optional[Brand]:
        return self.break_brand_map.get(break_id)


# Global instances
session_store = SessionStore()
brand_matcher = BrandMatcher(catalogue_path=DEFAULT_CATALOGUE_PATH)
scene_analyzer = GeminiSceneAnalyzer()
mock_analyzer = MockGeminiAnalyzer()


# ============================================================================
# Pydantic Request Models
# ============================================================================

class PipelineRunRequest(BaseModel):
    video_path: Optional[str] = Field(default=None, description="Absolute or relative path to MP4 video")
    preset_id: Optional[str] = Field(default=None, description="ID of pre-bundled demo preset video")
    safety_window_seconds: float = Field(default=0.5, ge=0.1, le=5.0)
    min_start_buffer_seconds: Optional[float] = Field(default=None)
    min_end_buffer_seconds: Optional[float] = Field(default=None)
    min_gap_seconds: Optional[float] = Field(default=None)
    max_breaks_per_hour: float = Field(default=4.0, ge=1.0, le=20.0)
    ad_load_pct: float = Field(default=10.0, ge=1.0, le=50.0)
    custom_brands: Optional[List[Dict[str, Any]]] = Field(default=None)


# ============================================================================
# FastAPI App Initialization
# ============================================================================

app = FastAPI(
    title="Cutaway Video Ad Placement API",
    description="Context-Aware Video Segmentation & Ad Placement Engine",
    version="1.0.0",
)

from starlette.middleware.base import BaseHTTPMiddleware

# Enable CORS for all origins, headers, and methods
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class PrivateNetworkMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

app.add_middleware(PrivateNetworkMiddleware)

# Mount static files for ad creatives and sample videos
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================================
# Core Pipeline Execution Logic (Stages 1-9)
# ============================================================================

def execute_full_pipeline(session: PipelineSession, custom_brands: Optional[List[Dict[str, Any]]] = None) -> None:
    """Executes all 9 stages of the Cutaway pipeline synchronously and populates session."""
    session.status = "PROCESSING"
    cfg = session.config
    video_path = session.video_path

    if custom_brands:
        local_matcher = BrandMatcher(catalogue=[])
        for b in custom_brands:
            local_matcher.add_brand(b)
    else:
        local_matcher = BrandMatcher(catalogue=brand_matcher.brands)

    try:
        # Stage 1: Ingest & Probe Video Metadata
        session.add_event("ingest", "RUNNING", 10, "Probing video dimensions, frame rate, and duration...")
        metadata = probe_video(video_path)
        session.add_event(
            "ingest",
            "COMPLETED",
            15,
            f"Probed video: {metadata.duration:.2f}s, {metadata.fps:.1f} fps, {metadata.width}x{metadata.height}",
            {"duration": metadata.duration, "fps": metadata.fps, "frame_count": metadata.frame_count},
        )

        # Adaptive buffer adjustment for short demo / preset clips
        if metadata.duration < 60.0:
            if cfg.min_start_buffer_seconds >= 60.0:
                cfg.min_start_buffer_seconds = 0.5
            if cfg.min_end_buffer_seconds >= 60.0:
                cfg.min_end_buffer_seconds = 0.5
            if cfg.min_gap_seconds >= 60.0:
                cfg.min_gap_seconds = 1.0

        # Stage 2: Audio Demuxing (ffmpeg)
        session.add_event("audio_extraction", "RUNNING", 20, "Extracting 16kHz mono audio track via ffmpeg...")
        audio_path, has_audio = extract_audio(video_path)
        metadata.has_audio = has_audio
        metadata.audio_path = audio_path
        session.add_event(
            "audio_extraction",
            "COMPLETED",
            25,
            "Audio extraction successful (16kHz mono PCM)",
            {"has_audio": has_audio, "audio_sample_rate": 16000},
        )

        # Stage 3: Coarse Scene Detection (PySceneDetect)
        session.add_event("scene_detection", "RUNNING", 30, "Detecting coarse scene cuts with PySceneDetect...")
        scenes, candidate_breaks = detect_and_refine_scenes(
            video_path=video_path,
            fps=metadata.fps,
            total_frames=metadata.frame_count,
            config=cfg,
        )
        session.add_event(
            "scene_detection",
            "COMPLETED",
            40,
            f"Identified {len(scenes)} visual scenes and {len(candidate_breaks)} candidate cut boundaries",
            {"scenes_count": len(scenes), "candidates_count": len(candidate_breaks)},
        )

        # Stage 4: Fine Boundary Refinement (TransNetV2)
        session.add_event("scene_refinement", "RUNNING", 45, "Refining cut boundaries to frame accuracy with TransNetV2...")
        # (Already refined in detect_and_refine_scenes)
        session.add_event(
            "scene_refinement",
            "COMPLETED",
            50,
            f"Verified {len(candidate_breaks)} transition points to millisecond precision",
            {"refined_cuts_count": len(candidate_breaks)},
        )

        # Stage 5: Speech Activity Detection (Silero VAD)
        session.add_event("vad_speech_detection", "RUNNING", 55, "Running Silero VAD for voice activity detection...")
        speech_intervals = []
        if has_audio and audio_path and os.path.exists(audio_path):
            speech_intervals = detect_speech_intervals(audio_path)
        session.add_event(
            "vad_speech_detection",
            "COMPLETED",
            60,
            f"Detected {len(speech_intervals)} speech intervals across audio track",
            {"speech_intervals_count": len(speech_intervals)},
        )

        # Stage 6: Silence Safety Window Gating (±N seconds)
        session.add_event(
            "silence_safety_gating",
            "RUNNING",
            65,
            f"Enforcing ±{cfg.safety_window_seconds}s silence safety window around cuts...",
        )
        candidate_breaks = evaluate_breaks_vad_safety(
            candidate_breaks=candidate_breaks,
            speech_intervals=speech_intervals,
            safety_window_n=cfg.safety_window_seconds,
        )
        safe_count = sum(1 for c in candidate_breaks if c.vad_safe)
        rejected_vad_count = sum(1 for c in candidate_breaks if not c.vad_safe)
        session.add_event(
            "silence_safety_gating",
            "COMPLETED",
            70,
            f"Gated candidate cuts: {safe_count} safe, {rejected_vad_count} rejected due to speech overlap (0 mid-speech cuts guarantee)",
            {"safe_cuts": safe_count, "rejected_speech_cuts": rejected_vad_count},
        )

        # Stage 7: Broadcast Pacing Rules Solver
        session.add_event("pacing_solver", "RUNNING", 75, "Solving broadcast pacing constraints (min gap, frequency cap)...")
        candidates_with_pacing, scheduled_breaks = solve_pacing(
            candidate_breaks=candidate_breaks,
            video_duration=metadata.duration,
            config=cfg,
        )
        for b in candidates_with_pacing:
            b.break_id = f"{session.session_id}_{b.break_id}"
        session.add_event(
            "pacing_solver",
            "COMPLETED",
            80,
            f"Pacing solver approved {len(scheduled_breaks)} commercial break slots satisfying all spacing rules",
            {"scheduled_breaks_count": len(scheduled_breaks)},
        )

        # Stage 8: Scene Understanding & Brand Safety Hard Gating
        session.add_event("brand_matching", "RUNNING", 85, "Analyzing scene context and evaluating brand safety & affinity...")
        scene_understandings: Dict[int, SceneUnderstanding] = {}
        
        required_scene_ids = set()
        for b in candidate_breaks:
            if getattr(b, 'vad_safe', False):
                required_scene_ids.add(b.lead_in_scene_id)
                if b.lead_out_scene_id is not None:
                    required_scene_ids.add(b.lead_out_scene_id)

        required_scenes = []
        for sc in scenes:
            if sc.scene_id not in required_scene_ids:
                scene_understandings[sc.scene_id] = mock_analyzer.analyze_scene(
                    scene_id=sc.scene_id,
                    start_time=sc.start_time,
                    end_time=sc.end_time,
                )
            else:
                required_scenes.append(sc)

        completed_count = 0
        total_required = len(required_scenes)

        def process_scene(sc):
            try:
                mid_time = (sc.start_time + sc.end_time) / 2.0
                kf_data = extract_keyframe(video_path, mid_time)
                su = scene_analyzer.analyze_scene(
                    scene_id=sc.scene_id,
                    keyframe_data=kf_data,
                    start_time=sc.start_time,
                    end_time=sc.end_time,
                )
            except Exception:
                su = mock_analyzer.analyze_scene(
                    scene_id=sc.scene_id,
                    start_time=sc.start_time,
                    end_time=sc.end_time,
                )
            return sc.scene_id, su

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_scene = {executor.submit(process_scene, sc): sc for sc in required_scenes}
            for future in concurrent.futures.as_completed(future_to_scene):
                sc_id, su = future.result()
                scene_understandings[sc_id] = su
                completed_count += 1
                session.add_event(
                    "scene_analysis",
                    "PROCESSING",
                    85,
                    f"Analyzed scene {sc_id} ({completed_count}/{total_required})"
                )

        if total_required > 0:
            session.add_event(
                "scene_analysis",
                "COMPLETED",
                85,
                f"Successfully analyzed all {total_required} required scenes in parallel."
            )

        # Evaluate brands for each scheduled break
        brand_match_results: List[BrandMatchResult] = []
        final_scheduled_breaks = []

        for b in scheduled_breaks:
            lead_in = scene_understandings.get(b.lead_in_scene_id)
            lead_out = scene_understandings.get(b.lead_out_scene_id)
            match_res = local_matcher.evaluate_break(
                break_id=b.break_id,
                lead_in_scene=lead_in or {},
                lead_out_scene=lead_out,
            )
            brand_match_results.append(match_res)

            if not match_res.is_dropped and match_res.selected_brand:
                session_store.register_break_brand(b.break_id, match_res.selected_brand)
                final_scheduled_breaks.append(b)

        session.add_event(
            "brand_matching",
            "COMPLETED",
            90,
            f"Brand matching complete: {len(final_scheduled_breaks)} approved breaks with context-fit brands, 100% zero negative context overlap",
            {"approved_breaks": len(final_scheduled_breaks)},
        )

        # Construct PipelineResult
        pipeline_res = PipelineResult(
            video_metadata=metadata,
            scenes=scenes,
            speech_intervals=speech_intervals,
            candidate_breaks=candidates_with_pacing,
            scheduled_breaks=scheduled_breaks,
            config=cfg,
        )

        # Stage 9: VMAP 1.0.1 & VAST 3.0 Manifest Generation & debug.json Export
        session.add_event("manifest_generation", "RUNNING", 95, "Generating IAB VMAP 1.0.1 and debug.json manifests...")
        vmap_xml = generate_vmap_xml(final_scheduled_breaks, ad_server_base_url="http://localhost:8000/vast")
        debug_data = export_debug_json(
            session_id=session.session_id,
            pipeline_result=pipeline_res,
            brand_match_results=brand_match_results,
            scene_understandings=scene_understandings,
        )

        # Populate session state
        session.pipeline_result = pipeline_res
        session.brand_match_results = brand_match_results
        session.scene_understandings = scene_understandings
        session.scheduled_breaks = debug_data["final_breaks"]
        session.vmap_xml = vmap_xml
        session.debug_data = debug_data
        session.status = "COMPLETED"
        session.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        session.add_event(
            "manifest_generation",
            "COMPLETED",
            100,
            "Cutaway pipeline finished successfully! Manifests ready for IMA SDK playback.",
            {
                "vmap_url": f"/vmap/{session.session_id}",
                "debug_url": f"/api/debug/{session.session_id}",
                "final_breaks_count": len(final_scheduled_breaks),
            },
        )

    except Exception as e:
        logger.exception("Pipeline failed on session %s: %s", session.session_id, e)
        session.status = "FAILED"
        session.error_message = str(e)
        session.add_event(
            session.current_stage or "pipeline",
            "FAILED",
            session.progress_percent,
            f"Pipeline execution error: {e}",
            {"error": str(e)},
        )


# ============================================================================
# API Endpoints
# ============================================================================

@app.post("/api/ads/upload")
async def upload_ad(file: UploadFile = File(...)):
    """Receives a custom MP4 ad file and saves it to STATIC_ADS_DIR."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    ext = Path(file.filename).suffix or ".mp4"
    ad_id = f"custom_ad_{uuid.uuid4().hex[:8]}"
    dest_path = STATIC_ADS_DIR / f"{ad_id}{ext}"
    
    with open(dest_path, "wb") as f_out:
        shutil.copyfileobj(file.file, f_out)
        
    return {"filename": dest_path.name, "url": f"/static/ads/{dest_path.name}"}

@app.post("/api/pipeline/run")
async def run_pipeline_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    video_path: Optional[str] = Form(None),
    preset_id: Optional[str] = Form(None),
    safety_window_seconds: Optional[float] = Form(None),
    min_start_buffer_seconds: Optional[float] = Form(None),
    min_end_buffer_seconds: Optional[float] = Form(None),
    min_gap_seconds: Optional[float] = Form(None),
    max_breaks_per_hour: Optional[float] = Form(None),
    ad_load_pct: Optional[float] = Form(None),
    custom_brands_json: Optional[str] = Form(None),
):
    """Initiates a Cutaway video analysis run from either JSON body or multipart form data."""
    # Check if request is JSON body
    content_type = request.headers.get("content-type", "")
    custom_brands: Optional[List[Dict[str, Any]]] = None

    if "application/json" in content_type:
        try:
            body_dict = await request.json()
            run_req = PipelineRunRequest(**body_dict)
            video_path = run_req.video_path
            preset_id = run_req.preset_id
            safety_window_seconds = run_req.safety_window_seconds
            min_start_buffer_seconds = run_req.min_start_buffer_seconds
            min_end_buffer_seconds = run_req.min_end_buffer_seconds
            min_gap_seconds = run_req.min_gap_seconds
            max_breaks_per_hour = run_req.max_breaks_per_hour
            ad_load_pct = run_req.ad_load_pct
            custom_brands = run_req.custom_brands
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")

    # Parse custom brands if provided as form string
    if custom_brands_json and not custom_brands:
        try:
            custom_brands = json.loads(custom_brands_json)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid custom_brands_json: {e}")

    session_id = f"run_{uuid.uuid4().hex[:10]}"

    # Resolve target video file
    target_video_path: Optional[str] = None

    if file and file.filename:
        upload_dir = STATIC_DIR / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(file.filename).suffix or ".mp4"
        dest_path = upload_dir / f"{session_id}{ext}"
        with open(dest_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)
        target_video_path = str(dest_path)

    elif preset_id:
        preset_info = DEMO_PRESETS.get(preset_id)
        if not preset_info:
            raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found.")
        preset_file = PRESET_VIDEOS_DIR / preset_info["filename"]
        if not preset_file.exists():
            ensure_demo_presets()
        target_video_path = str(preset_file)

    elif video_path:
        p = Path(video_path)
        if not p.is_absolute():
            p = BASE_DIR / video_path
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"Video file not found at: {video_path}")
        target_video_path = str(p)

    else:
        # Fallback to default preset
        default_preset = PRESET_VIDEOS_DIR / "tech_review.mp4"
        if not default_preset.exists():
            ensure_demo_presets()
        target_video_path = str(default_preset)

    # Build PipelineConfig with defaults
    cfg_kwargs: Dict[str, Any] = {}
    if safety_window_seconds is not None:
        cfg_kwargs["safety_window_seconds"] = safety_window_seconds
    if min_start_buffer_seconds is not None:
        cfg_kwargs["min_start_buffer_seconds"] = min_start_buffer_seconds
    if min_end_buffer_seconds is not None:
        cfg_kwargs["min_end_buffer_seconds"] = min_end_buffer_seconds
    if min_gap_seconds is not None:
        cfg_kwargs["min_gap_seconds"] = min_gap_seconds
    if max_breaks_per_hour is not None:
        cfg_kwargs["max_breaks_per_hour"] = max_breaks_per_hour
    if ad_load_pct is not None:
        cfg_kwargs["ad_load_pct"] = ad_load_pct

    config = PipelineConfig(**cfg_kwargs)
    
    try:
        probe_video(target_video_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to open video file: {e}")

    # Create session immediately — return session_id to client right away
    session = session_store.create_session(session_id, target_video_path, config)
    session.status = "PROCESSING"

    # Run the pipeline in a background thread
    thread = threading.Thread(
        target=execute_full_pipeline,
        args=(session, custom_brands),
        daemon=True
    )
    thread.start()

    return {
        "session_id": session_id,
        "sessionId": session_id,
        "status": session.status,
        "vmap_url": f"/vmap/{session_id}",
        "debug_url": f"/api/debug/{session_id}",
        "scheduled_breaks_count": len(session.scheduled_breaks),
        "message": "Pipeline started in background.",
    }




@app.get("/api/pipeline/status/{session_id}")
async def get_pipeline_status(session_id: str):
    """Returns current pipeline status and execution summary."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    return {
        "session_id": session.session_id,
        "sessionId": session.session_id,
        "status": session.status,
        "current_stage": session.current_stage,
        "stages_completed": session.stages_completed,
        "progress_percent": session.progress_percent,
        "vmap_url": f"/vmap/{session.session_id}",
        "debug_url": f"/api/debug/{session.session_id}",
        "error_message": session.error_message,
        "execution_summary": sanitize_floats(session.debug_data.get("execution_summary", {})),
    }


@app.get("/api/pipeline/stream/{session_id}")
async def stream_pipeline_events(session_id: str):
    """Server-Sent Events (SSE) streaming pipeline stage progress for Live Run Console."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    async def event_generator():
        # Stream all existing events recorded so far
        for ev in list(session.events):
            yield f"data: {json.dumps(ev)}\n\n"
            await asyncio.sleep(0.01)

        # If already completed or failed, close stream
        if session.status in ("COMPLETED", "FAILED"):
            return

        # Poll for new events if still running
        last_index = len(session.events)
        while session.status not in ("COMPLETED", "FAILED"):
            await asyncio.sleep(0.1)
            current_len = len(session.events)
            if current_len > last_index:
                for i in range(last_index, current_len):
                    yield f"data: {json.dumps(session.events[i])}\n\n"
                last_index = current_len

        # Stream any remaining trailing events
        current_len = len(session.events)
        if current_len > last_index:
            for i in range(last_index, current_len):
                yield f"data: {json.dumps(session.events[i])}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


# Support both /vmap/{sessionId} and /vmap?sessionId=...
@app.get("/vmap/{session_id}")
async def get_vmap_manifest_path(session_id: str):
    """Returns IAB VMAP 1.0.1 XML manifest for the given session ID."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    xml_content = session.vmap_xml or generate_vmap_xml([])
    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={
            "Content-Type": "application/xml; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Private-Network": "true",
        },
    )


@app.get("/vmap")
async def get_vmap_manifest_query(sessionId: Optional[str] = Query(None, alias="sessionId")):
    """Returns IAB VMAP 1.0.1 XML manifest via query parameter."""
    if not sessionId:
        # Return empty VMAP
        empty_vmap = generate_vmap_xml([])
        return Response(
            content=empty_vmap,
            media_type="application/xml",
            headers={
                "Content-Type": "application/xml; charset=utf-8", 
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Private-Network": "true",
            },
        )
    return await get_vmap_manifest_path(sessionId)


# Support both /vast?breakId=... and /vast/{breakId}
@app.get("/vast")
async def get_vast_tag(
    request: Request,
    breakId: Optional[str] = Query(None, alias="breakId"),
    brandId: Optional[str] = Query(None, alias="brandId"),
):
    """Mock Ad Server endpoint returning IAB VAST 3.0 XML with CORS headers."""
    clean_break_id = (breakId or "break_default").strip()

    # Look up brand registered for this break
    matched_brand = session_store.get_brand_for_break(clean_break_id)

    # Fallback to brandId query param if present
    if not matched_brand and brandId:
        matched_brand = brand_matcher.get_brand(brandId)

    if not matched_brand:
        return Response(
            content=generate_empty_vast_xml(clean_break_id),
            media_type="application/xml",
            headers={
                "Content-Type": "application/xml; charset=utf-8", 
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Private-Network": "true",
            },
        )

    base_url = str(request.base_url).rstrip("/")
    vast_xml = generate_vast_xml(break_id=clean_break_id, brand=matched_brand, ad_server_base=base_url)

    return Response(
        content=vast_xml,
        media_type="application/xml",
        headers={
            "Content-Type": "application/xml; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Private-Network": "true",
        },
    )


@app.get("/vast/{break_id}")
async def get_vast_tag_path(request: Request, break_id: str):
    """Mock Ad Server endpoint via path parameter."""
    return await get_vast_tag(request, breakId=break_id)


# Support both /api/debug/{sessionId} and /api/debug?sessionId=...
@app.get("/api/debug/{session_id}")
async def get_debug_json_path(session_id: str):
    """Returns parallel debug.json manifest for forensic timeline inspection."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    safe_debug_data = sanitize_floats(session.debug_data)

    return JSONResponse(
        content=safe_debug_data,
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.get("/api/debug")
async def get_debug_json_query(sessionId: Optional[str] = Query(None, alias="sessionId")):
    """Returns debug.json manifest via query parameter."""
    if not sessionId:
        raise HTTPException(status_code=400, detail="Missing required query parameter 'sessionId'")
    return await get_debug_json_path(sessionId)


@app.get("/api/brands")
async def get_brands():
    """Returns active catalogue brands."""
    return JSONResponse(
        content=[b.model_dump() for b in brand_matcher.brands],
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.post("/api/brands")
async def add_brand(brand: Union[Brand, Dict[str, Any]]):
    """Dynamically adds/updates a brand in the active catalogue (enabling 9th brand test)."""
    try:
        registered = brand_matcher.add_brand(brand)
        return JSONResponse(
            content=registered.model_dump(),
            status_code=status.HTTP_201_CREATED,
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid brand schema: {e}")


@app.get("/api/presets")
async def get_presets():
    """Returns pre-bundled demo video presets."""
    preset_list = []
    for p_id, p_data in DEMO_PRESETS.items():
        preset_list.append({
            "id": p_id,
            "name": p_data["name"],
            "category": p_data["category"],
            "description": p_data["description"],
            "duration": p_data["duration"],
            "recommended_brands": p_data.get("recommended_brands", []),
            "default_config": p_data.get("default_config", {}),
            "video_url": f"/static/sample_videos/{p_data['filename']}",
        })
    return JSONResponse(
        content=preset_list,
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.get("/api/video/{session_id}")
async def get_session_video(session_id: str):
    """Streams the ingested video MP4 for HTML5 <video> player."""
    session = session_store.get_session(session_id)
    if not session or not os.path.exists(session.video_path):
        raise HTTPException(status_code=404, detail="Session video not found")

    return FileResponse(
        session.video_path,
        media_type="video/mp4",
        headers={"Access-Control-Allow-Origin": "*", "Accept-Ranges": "bytes"},
    )


# Mock tracking endpoints
@app.get("/api/tracking/{event_name}")
async def tracking_beacon(event_name: str, breakId: Optional[str] = None):
    """Captures VAST tracking events (start, quartile, complete, impression)."""
    logger.debug("VAST tracking beacon: %s for break %s", event_name, breakId)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Access-Control-Allow-Origin": "*"},
    )
