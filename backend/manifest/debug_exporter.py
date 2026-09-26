"""Parallel Debug Manifest Exporter (debug.json).

Compiles and exports comprehensive forensic algorithmic trace data for Cutaway:
- Video metadata (duration, fps, total_frames, dimensions, audio properties)
- Scenes (start/end timecodes, dominant activity, setting, sentiment, GARM safety tags, objects)
- Silero VAD speech intervals and safety window boundaries
- Candidate breaks (cut time, vad_safe, nearest speech gap, pacing validity, status, rejection reason)
- Selected / Final breaks (breakId, timeOffset, winning brand, score, evaluation matrix)
- Brand evaluations per candidate break (positive matches, negative intersections, gated status)
- Execution summary metrics
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.manifest.vmap_generator import format_seconds_to_timecode
from backend.models.brand_models import Brand, BrandEvaluation, BrandMatchResult, SceneUnderstanding
from backend.models.pipeline_models import (
    CandidateBreak,
    PipelineConfig,
    PipelineResult,
    SceneBoundary,
    SpeechInterval,
    VideoMetadata,
)


def _serialize_metadata(video_meta: Union[VideoMetadata, Dict[str, Any]]) -> Dict[str, Any]:
    """Ensures video metadata contains all expected fields with total_frames."""
    if isinstance(video_meta, VideoMetadata):
        data = video_meta.model_dump()
    elif isinstance(video_meta, dict):
        data = dict(video_meta)
    else:
        raise TypeError(f"Unsupported video metadata type: {type(video_meta)}")

    # Ensure total_frames key is present (alias for frame_count if needed)
    if "total_frames" not in data:
        data["total_frames"] = data.get("frame_count", int(round(data.get("duration", 0) * data.get("fps", 30))))
    if "frame_count" not in data:
        data["frame_count"] = data.get("total_frames", 0)

    # Defaults for dimensions and audio
    data.setdefault("width", 1280)
    data.setdefault("height", 720)
    data.setdefault("has_audio", True)
    data.setdefault("audio_sample_rate", 16000)

    return data


def _serialize_scene(
    scene: Union[SceneBoundary, SceneUnderstanding, Dict[str, Any]],
    scene_understanding_map: Optional[Dict[int, SceneUnderstanding]] = None,
) -> Dict[str, Any]:
    """Serializes a scene boundary enriched with semantic understanding if available."""
    if isinstance(scene, (SceneBoundary, SceneUnderstanding)):
        s_dict = scene.model_dump()
    elif isinstance(scene, dict):
        s_dict = dict(scene)
    else:
        s_dict = {}

    scene_id = s_dict.get("scene_id", 0)

    # Enrich from scene_understanding_map if provided
    su = scene_understanding_map.get(scene_id) if scene_understanding_map else None
    if su:
        su_dict = su.model_dump()
        for k in (
            "dominant_activity",
            "setting",
            "sentiment",
            "garm_safety_tags",
            "contextual_tags",
            "key_objects",
            "brand_suitability_summary",
        ):
            if k in su_dict and su_dict[k]:
                s_dict[k] = su_dict[k]

    # Defaults for required fields
    s_dict.setdefault("dominant_activity", "General scene activity")
    s_dict.setdefault("setting", "Unspecified setting")
    s_dict.setdefault("sentiment", "neutral")
    s_dict.setdefault("garm_safety_tags", ["safe_all_audiences"])
    s_dict.setdefault("garm_tags", s_dict["garm_safety_tags"])
    s_dict.setdefault("contextual_tags", [])
    s_dict.setdefault("key_objects", [])

    return s_dict


def _serialize_speech(interval: Union[SpeechInterval, Tuple[float, float], List[float], Dict[str, Any]]) -> Dict[str, Any]:
    """Serializes a speech interval ensuring start_time and end_time."""
    if isinstance(interval, SpeechInterval):
        return {"start_time": interval.start_time, "end_time": interval.end_time, "confidence": interval.confidence}
    elif isinstance(interval, (tuple, list)) and len(interval) >= 2:
        return {"start_time": float(interval[0]), "end_time": float(interval[1]), "confidence": 1.0}
    elif isinstance(interval, dict):
        return {
            "start_time": float(interval.get("start_time", 0.0)),
            "end_time": float(interval.get("end_time", 0.0)),
            "confidence": float(interval.get("confidence", 1.0)),
        }
    else:
        return {"start_time": 0.0, "end_time": 0.0, "confidence": 1.0}


def _serialize_candidate(cb: Union[CandidateBreak, Dict[str, Any]]) -> Dict[str, Any]:
    """Serializes a candidate break."""
    if isinstance(cb, CandidateBreak):
        data = cb.model_dump()
    elif isinstance(cb, dict):
        data = dict(cb)
    else:
        data = {}

    data.setdefault("break_id", "break_unknown")
    data.setdefault("cut_time", 0.0)
    data.setdefault("lead_in_scene_id", 0)
    data.setdefault("lead_out_scene_id", 1)
    data.setdefault("vad_safe", True)
    data.setdefault("nearest_speech_gap", 999.0)
    data.setdefault("pacing_valid", True)
    data.setdefault("status", "CANDIDATE")
    data.setdefault("rejection_reason", None)

    return data


def build_debug_json(
    session_id: str,
    video_meta: Union[VideoMetadata, Dict[str, Any]],
    scenes: List[Any],
    speech_intervals: List[Any],
    candidate_breaks: List[Any],
    final_breaks: List[Any],
    brand_evaluations: Optional[Dict[str, List[Any]]] = None,
    scene_understandings: Optional[Dict[int, SceneUnderstanding]] = None,
    config: Optional[Union[PipelineConfig, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Constructs the canonical debug.json structure conforming to all specification contracts."""
    meta_dict = _serialize_metadata(video_meta)
    serialized_scenes = [_serialize_scene(s, scene_understandings) for s in scenes]
    serialized_speech = [_serialize_speech(sp) for sp in speech_intervals]
    serialized_candidates = [_serialize_candidate(cb) for cb in candidate_breaks]

    serialized_final: List[Dict[str, Any]] = []
    for fb in final_breaks:
        if isinstance(fb, dict):
            b_dict = dict(fb)
        elif isinstance(fb, CandidateBreak):
            b_dict = fb.model_dump()
        else:
            b_dict = getattr(fb, "__dict__", {}).copy()

        cut_t = float(b_dict.get("cut_time", 0.0))
        time_offset = b_dict.get("time_offset") or b_dict.get("timeOffset") or format_seconds_to_timecode(cut_t)
        b_dict["time_offset"] = time_offset
        b_dict["timeOffset"] = time_offset

        # Standardize matched brand
        matched = b_dict.get("matched_brand")
        if isinstance(matched, Brand):
            b_dict["matched_brand"] = matched.model_dump()
        elif matched is None and "brand" in b_dict:
            b_dict["matched_brand"] = b_dict["brand"]

        # Ensure status is SELECTED for scheduled breaks
        if b_dict.get("status") in (None, "CANDIDATE"):
            b_dict["status"] = "SELECTED"

        serialized_final.append(b_dict)

    # Map candidate break status for those that became selected
    selected_map = {b["break_id"]: b for b in serialized_final}
    for c in serialized_candidates:
        if c["break_id"] in selected_map:
            c["status"] = "SELECTED"
            final_b = selected_map[c["break_id"]]
            if "matched_brand" in final_b:
                c["matched_brand"] = final_b["matched_brand"]
            if "brand_score" in final_b:
                c["brand_score"] = final_b["brand_score"]

    # Brand evaluations map
    eval_map: Dict[str, List[Dict[str, Any]]] = {}
    if brand_evaluations:
        for b_id, ev_list in brand_evaluations.items():
            eval_map[b_id] = [
                ev.model_dump() if isinstance(ev, BrandEvaluation) else dict(ev) for ev in ev_list
            ]

    # Config serialization
    cfg_dict = config.model_dump() if isinstance(config, PipelineConfig) else (config or {})

    # Execution summary
    selected_count = len(serialized_final)
    rejected_count = sum(1 for c in serialized_candidates if c.get("status", "").startswith("REJECTED") or c.get("status") == "DROPPED_ALL_BRANDS_GATED")

    return {
        "session_id": session_id,
        "video_metadata": meta_dict,
        "scenes": serialized_scenes,
        "speech_intervals": serialized_speech,
        "candidate_breaks": serialized_candidates,
        "final_breaks": serialized_final,
        "selected_breaks": serialized_final,  # alias for frontend / inspection
        "brand_evaluations": eval_map,
        "pipeline_config": cfg_dict,
        "execution_summary": {
            "total_scenes": len(serialized_scenes),
            "total_speech_intervals": len(serialized_speech),
            "candidate_break_count": len(serialized_candidates),
            "selected_break_count": selected_count,
            "rejected_break_count": rejected_count,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }


def export_debug_json(
    session_id: str,
    pipeline_result: PipelineResult,
    brand_match_results: Optional[List[BrandMatchResult]] = None,
    scene_understandings: Optional[Dict[int, SceneUnderstanding]] = None,
) -> Dict[str, Any]:
    """Generates a complete debug.json dictionary from PipelineResult and brand match results."""
    # Build final breaks with attached matched brand info
    final_breaks: List[Dict[str, Any]] = []
    brand_eval_map: Dict[str, List[Any]] = {}

    match_map: Dict[str, BrandMatchResult] = {}
    if brand_match_results:
        for bmr in brand_match_results:
            match_map[bmr.break_id] = bmr
            brand_eval_map[bmr.break_id] = bmr.evaluations

    for sb in pipeline_result.scheduled_breaks:
        sb_dict = sb.model_dump()
        bmr = match_map.get(sb.break_id)

        if bmr and bmr.is_dropped:
            # Dropped due to brand safety gating / zero score
            sb_dict["status"] = "DROPPED_ALL_BRANDS_GATED"
            sb_dict["rejection_reason"] = bmr.reason
            continue

        if bmr and bmr.selected_brand:
            sb_dict["matched_brand"] = bmr.selected_brand.model_dump()
            sb_dict["brand_score"] = bmr.winning_score
            sb_dict["evaluations"] = [ev.model_dump() for ev in bmr.evaluations]
        else:
            sb_dict["matched_brand"] = None
            sb_dict["brand_score"] = 0.0
            sb_dict["evaluations"] = []

        sb_dict["status"] = "SELECTED"
        final_breaks.append(sb_dict)

    return build_debug_json(
        session_id=session_id,
        video_meta=pipeline_result.video_metadata,
        scenes=pipeline_result.scenes,
        speech_intervals=pipeline_result.speech_intervals,
        candidate_breaks=pipeline_result.candidate_breaks,
        final_breaks=final_breaks,
        brand_evaluations=brand_eval_map,
        scene_understandings=scene_understandings,
        config=pipeline_result.config,
    )


def save_debug_json(debug_dict: Dict[str, Any], filepath: Union[str, Path]) -> str:
    """Saves the debug manifest dictionary to a JSON file."""
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(debug_dict, f, indent=2)
    return str(p)


def validate_debug_manifest(debug_data: Dict[str, Any]) -> bool:
    """Validates structural invariants of debug.json."""
    required = ["session_id", "video_metadata", "scenes", "speech_intervals", "candidate_breaks", "final_breaks"]
    for k in required:
        if k not in debug_data:
            raise ValueError(f"Missing required key '{k}' in debug.json")

    meta = debug_data["video_metadata"]
    for mk in ["duration", "fps", "total_frames"]:
        if mk not in meta:
            raise ValueError(f"Missing '{mk}' in video_metadata")
    if meta["duration"] <= 0:
        raise ValueError("video_metadata.duration must be positive")

    for sc in debug_data["scenes"]:
        for sk in ["scene_id", "start_time", "end_time"]:
            if sk not in sc:
                raise ValueError(f"Scene missing key '{sk}'")
        if sc["start_time"] > sc["end_time"]:
            raise ValueError(f"Scene {sc['scene_id']} start_time > end_time")

    for sp in debug_data["speech_intervals"]:
        if "start_time" not in sp or "end_time" not in sp:
            raise ValueError("Speech interval missing start_time or end_time")
        if sp["start_time"] > sp["end_time"]:
            raise ValueError("Speech interval start_time > end_time")

    for cb in debug_data["candidate_breaks"]:
        for ck in ["break_id", "cut_time", "vad_safe", "pacing_valid", "status"]:
            if ck not in cb:
                raise ValueError(f"Candidate break missing key '{ck}'")
        if cb["status"] not in ("CANDIDATE", "REJECTED_VAD", "REJECTED_PACING", "DROPPED_ALL_BRANDS_GATED", "SELECTED"):
            raise ValueError(f"Unknown break status: {cb['status']}")

    return True
