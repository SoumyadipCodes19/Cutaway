from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import scipy.signal
import soundfile as sf
import torch

from backend.models.pipeline_models import (
    CandidateBreak,
    PipelineConfig,
    PipelineResult,
    SpeechInterval,
    VideoMetadata,
)
from backend.pipeline.ingest import extract_audio, probe_video
from backend.pipeline.pacing import solve_pacing
from backend.pipeline.scene_detector import detect_and_refine_scenes

logger = logging.getLogger(__name__)

# Global singleton cache for Silero VAD model and utils
_VAD_MODEL = None
_VAD_UTILS: Optional[Tuple[Callable, ...]] = None


def load_silero_vad(
    onnx: bool = True,
    force_reload: bool = False,
) -> Tuple[Any, Optional[Tuple[Callable, ...]]]:
    """
    Loads Silero VAD model on CPU with graceful multi-tier fallbacks:
    1. Local torch hub cache directory (~/.cache/torch/hub/snakers4_silero-vad_master)
    2. Remote torch hub repo ('snakers4/silero-vad')
    3. ONNX runtime -> PyTorch CPU JIT fallback if onnx fails
    4. Energy-based fallback if torch hub fails completely.

    Returns:
        (model, utils_tuple)
    """
    global _VAD_MODEL, _VAD_UTILS

    if _VAD_MODEL is not None and not force_reload:
        return _VAD_MODEL, _VAD_UTILS

    # 1. Try local torch hub cache path
    cache_dirs = [
        os.path.expanduser("~/.cache/torch/hub/snakers4_silero-vad_master"),
        os.path.expanduser("~/.cache/torch/hub/snakers4_silero-vad_v4"),
        os.path.expanduser("~/.cache/torch/hub/snakers4_silero-vad_v5"),
    ]

    for c_dir in cache_dirs:
        if os.path.isdir(c_dir):
            try:
                model, utils = torch.hub.load(
                    c_dir,
                    "silero_vad",
                    source="local",
                    onnx=onnx,
                    trust_repo=True,
                )
                _VAD_MODEL = model
                _VAD_UTILS = utils
                logger.info("Loaded Silero VAD from local cache: %s (onnx=%s)", c_dir, onnx)
                return _VAD_MODEL, _VAD_UTILS
            except Exception as e:
                logger.warning("Failed loading Silero VAD from local cache %s: %s", c_dir, e)
                # Try fallback to onnx=False (PyTorch JIT)
                if onnx:
                    try:
                        model, utils = torch.hub.load(
                            c_dir,
                            "silero_vad",
                            source="local",
                            onnx=False,
                            trust_repo=True,
                        )
                        _VAD_MODEL = model
                        _VAD_UTILS = utils
                        logger.info("Loaded Silero VAD PyTorch JIT fallback from local cache: %s", c_dir)
                        return _VAD_MODEL, _VAD_UTILS
                    except Exception as e2:
                        logger.warning("Local PyTorch JIT fallback also failed: %s", e2)

    # 2. Try remote torch hub repo
    try:
        model, utils = torch.hub.load(
            "snakers4/silero-vad",
            "silero_vad",
            onnx=onnx,
            trust_repo=True,
        )
        _VAD_MODEL = model
        _VAD_UTILS = utils
        logger.info("Loaded Silero VAD from remote hub (onnx=%s)", onnx)
        return _VAD_MODEL, _VAD_UTILS
    except Exception as e:
        logger.warning("Remote torch hub loading failed with onnx=%s: %s", onnx, e)
        if onnx:
            try:
                model, utils = torch.hub.load(
                    "snakers4/silero-vad",
                    "silero_vad",
                    onnx=False,
                    trust_repo=True,
                )
                _VAD_MODEL = model
                _VAD_UTILS = utils
                logger.info("Loaded Silero VAD from remote hub (PyTorch JIT)")
                return _VAD_MODEL, _VAD_UTILS
            except Exception as e2:
                logger.warning("Remote torch hub PyTorch JIT also failed: %s", e2)

    logger.warning("Silero VAD model could not be loaded via torch hub. Using energy-based VAD fallback.")
    _VAD_MODEL = None
    _VAD_UTILS = None
    return None, None


def _energy_vad(
    audio: np.ndarray,
    sample_rate: int = 16000,
    frame_duration_ms: int = 30,
    energy_threshold: float = 0.015,
    min_speech_duration_s: float = 0.25,
    min_silence_duration_s: float = 0.10,
) -> List[SpeechInterval]:
    """
    Genuine fallback voice activity detector using Root-Mean-Square (RMS)
    signal energy over 30ms frames. Merges short silences and filters noise bursts.
    """
    if len(audio) == 0:
        return []

    frame_len = int(sample_rate * (frame_duration_ms / 1000.0))
    if frame_len <= 0:
        return []

    num_frames = len(audio) // frame_len
    if num_frames == 0:
        return []

    frames = audio[: num_frames * frame_len].reshape(num_frames, frame_len)
    rms = np.sqrt(np.mean(frames**2, axis=1))

    # Binary speech mask
    is_speech = rms > energy_threshold

    # Find raw contiguous active blocks
    raw_segments: List[Tuple[float, float]] = []
    in_speech = False
    start_t = 0.0

    for i, active in enumerate(is_speech):
        t_sec = i * (frame_duration_ms / 1000.0)
        if active and not in_speech:
            in_speech = True
            start_t = t_sec
        elif not active and in_speech:
            in_speech = False
            raw_segments.append((start_t, t_sec))

    if in_speech:
        raw_segments.append((start_t, num_frames * (frame_duration_ms / 1000.0)))

    if not raw_segments:
        return []

    # Merge silences shorter than min_silence_duration_s
    merged: List[Tuple[float, float]] = [raw_segments[0]]
    for cur_s, cur_e in raw_segments[1:]:
        prev_s, prev_e = merged[-1]
        if (cur_s - prev_e) < min_silence_duration_s:
            merged[-1] = (prev_s, cur_e)
        else:
            merged.append((cur_s, cur_e))

    # Filter out segments shorter than min_speech_duration_s
    final_intervals: List[SpeechInterval] = []
    for s, e in merged:
        if (e - s) >= min_speech_duration_s:
            final_intervals.append(
                SpeechInterval(
                    start_time=round(s, 3),
                    end_time=round(e, 3),
                    confidence=0.85,
                )
            )

    return final_intervals


def load_audio_tensor(
    audio_input: Union[str, Path, np.ndarray, torch.Tensor],
    target_sr: int = 16000,
    source_sr: Optional[int] = None,
) -> Tuple[torch.Tensor, int]:
    """
    Loads, normalizes, and resamples audio to a 1D float32 torch.Tensor at target_sr (16kHz).
    """
    if isinstance(audio_input, (str, Path)):
        path_str = str(audio_input)
        if not os.path.exists(path_str):
            raise FileNotFoundError(f"Audio file does not exist: {path_str}")

        if os.path.getsize(path_str) <= 44:
            return torch.zeros(0, dtype=torch.float32), target_sr

        audio, sr = sf.read(path_str, dtype="float32")
    elif isinstance(audio_input, torch.Tensor):
        audio = audio_input.detach().cpu().numpy()
        sr = source_sr or target_sr
    elif isinstance(audio_input, np.ndarray):
        audio = audio_input
        sr = source_sr or target_sr
    else:
        raise TypeError(f"Unsupported audio input type: {type(audio_input)}")

    # Downmix stereo/multichannel to mono
    if audio.ndim > 1:
        audio = np.mean(audio, axis=-1)

    # Convert integer PCM to float [-1.0, 1.0] if necessary
    if np.issubdtype(audio.dtype, np.integer):
        max_val = float(np.iinfo(audio.dtype).max)
        audio = audio.astype(np.float32) / max_val
    else:
        audio = audio.astype(np.float32)

    # Resample if sample rate differs from target_sr
    if sr != target_sr and len(audio) > 0:
        num_target_samples = int(round(len(audio) * float(target_sr) / float(sr)))
        audio = scipy.signal.resample(audio, num_target_samples).astype(np.float32)
        sr = target_sr

    # Ensure float32 bounds [-1.0, 1.0]
    audio = np.clip(audio, -1.0, 1.0)
    return torch.from_numpy(audio), target_sr


def detect_speech_intervals(
    audio_input: Union[str, Path, np.ndarray, torch.Tensor],
    sample_rate: int = 16000,
    threshold: float = 0.5,
    min_speech_duration_ms: int = 250,
    min_silence_duration_ms: int = 100,
    onnx: bool = True,
) -> List[SpeechInterval]:
    """
    Runs Silero VAD speech activity detection over audio and returns millisecond-precision
    SpeechInterval objects.
    """
    audio_tensor, sr = load_audio_tensor(audio_input, target_sr=16000, source_sr=sample_rate)
    if audio_tensor.numel() == 0:
        return []

    model, utils = load_silero_vad(onnx=onnx)

    if model is not None and utils is not None:
        try:
            get_speech_timestamps = utils[0]
            raw_timestamps = get_speech_timestamps(
                audio_tensor,
                model,
                threshold=threshold,
                sampling_rate=sr,
                min_speech_duration_ms=min_speech_duration_ms,
                min_silence_duration_ms=min_silence_duration_ms,
                return_seconds=True,
            )

            speech_intervals: List[SpeechInterval] = []
            for item in raw_timestamps:
                st = round(float(item["start"]), 3)
                et = round(float(item["end"]), 3)
                if et > st:
                    speech_intervals.append(
                        SpeechInterval(
                            start_time=st,
                            end_time=et,
                            confidence=1.0,
                        )
                    )
            return speech_intervals
        except Exception as e:
            logger.warning("Silero VAD execution encountered error: %s. Falling back to energy VAD.", e)

    # Fallback to energy-based VAD
    audio_np = audio_tensor.numpy()
    return _energy_vad(
        audio_np,
        sample_rate=sr,
        min_speech_duration_s=min_speech_duration_ms / 1000.0,
        min_silence_duration_s=min_silence_duration_ms / 1000.0,
    )


def evaluate_silence_window(
    cut_time: float,
    speech_intervals: List[Union[SpeechInterval, Tuple[float, float]]],
    safety_window_n: float = 0.5,
) -> Dict[str, Any]:
    """
    Evaluates whether candidate cut_time satisfies the ±N second silence safety window.

    Safety window: W = [cut_time - N, cut_time + N].
    A candidate cut is VAD-SAFE if and only if no speech interval intersects W:
        for all [s, e] in speech_intervals: max(cut_time - N, s) >= min(cut_time + N, e)

    Returns:
        dict with keys:
            - vad_safe (bool)
            - status (str: "CANDIDATE" or "REJECTED_SPEECH_OVERLAP")
            - nearest_speech_gap (float)
            - safety_margin_violated (float)
            - overlapping_speech (Optional[Tuple[float, float]])
            - safety_window (Tuple[float, float])
            - reason (str)
    """
    w_start = cut_time - safety_window_n
    w_end = cut_time + safety_window_n

    nearest_prev_speech_end = -1.0
    nearest_next_speech_start = float("inf")
    overlap_interval: Optional[Tuple[float, float]] = None
    overlap_duration = 0.0

    normalized_intervals: List[Tuple[float, float]] = []
    for item in speech_intervals:
        if isinstance(item, SpeechInterval):
            normalized_intervals.append((item.start_time, item.end_time))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            normalized_intervals.append((float(item[0]), float(item[1])))

    for s_start, s_end in normalized_intervals:
        # Distance tracking
        if s_end <= cut_time:
            if s_end > nearest_prev_speech_end:
                nearest_prev_speech_end = s_end
        if s_start >= cut_time:
            if s_start < nearest_next_speech_start:
                nearest_next_speech_start = s_start

        # Check intersection between [w_start, w_end] and [s_start, s_end]
        intersect_start = max(w_start, s_start)
        intersect_end = min(w_end, s_end)
        if intersect_start < intersect_end:
            overlap_interval = (round(s_start, 3), round(s_end, 3))
            overlap_duration = intersect_end - intersect_start
            break

    if overlap_interval is not None:
        return {
            "vad_safe": False,
            "status": "REJECTED_SPEECH_OVERLAP",
            "nearest_speech_gap": 0.0,
            "safety_margin_violated": round(overlap_duration, 4),
            "overlapping_speech": overlap_interval,
            "safety_window": (round(w_start, 3), round(w_end, 3)),
            "reason": (
                f"REJECTED_SPEECH_OVERLAP: Speech interval {overlap_interval} "
                f"overlaps silence window [{w_start:.2f}, {w_end:.2f}] by {overlap_duration:.3f}s"
            ),
        }

    # Safe: compute distance to nearest speech boundary
    delta_prev = (cut_time - nearest_prev_speech_end) if nearest_prev_speech_end >= 0 else float("inf")
    delta_next = (nearest_next_speech_start - cut_time) if nearest_next_speech_start < float("inf") else float("inf")
    nearest_gap = min(delta_prev, delta_next)

    return {
        "vad_safe": True,
        "status": "CANDIDATE",
        "nearest_speech_gap": round(nearest_gap, 4) if not math.isinf(nearest_gap) else 999.0,
        "safety_margin_violated": 0.0,
        "overlapping_speech": None,
        "safety_window": (round(w_start, 3), round(w_end, 3)),
        "reason": "Clear of speech in ±N silence window",
    }


def evaluate_breaks_vad_safety(
    candidate_breaks: List[CandidateBreak],
    speech_intervals: List[Union[SpeechInterval, Tuple[float, float]]],
    safety_window_n: float = 0.5,
) -> List[CandidateBreak]:
    """
    Applies silence window safety gating to all candidate breaks.
    Updates each CandidateBreak with vad_safe, nearest_speech_gap, status, and rejection_reason.
    """
    updated: List[CandidateBreak] = []

    for b in candidate_breaks:
        b_copy = b.model_copy()
        res = evaluate_silence_window(
            cut_time=b_copy.cut_time,
            speech_intervals=speech_intervals,
            safety_window_n=safety_window_n,
        )

        b_copy.vad_safe = res["vad_safe"]
        b_copy.nearest_speech_gap = res["nearest_speech_gap"]

        if res["vad_safe"]:
            b_copy.status = "CANDIDATE"
            b_copy.rejection_reason = None
        else:
            b_copy.status = "REJECTED_VAD"
            b_copy.rejection_reason = res["reason"]
            b_copy.pacing_valid = False

        updated.append(b_copy)

    return updated


def run_pipeline(
    video_path: str,
    config: Optional[PipelineConfig] = None,
) -> PipelineResult:
    """
    Orchestrates Milestone 1 full pipeline:
    1. Media Ingest & metadata probing (ffmpeg / OpenCV)
    2. 16kHz mono audio extraction (ffmpeg)
    3. Coarse-to-fine visual scene segmentation (PySceneDetect + TransNetV2)
    4. Silero VAD speech detection
    5. Silence safety window gating (±N sec window, 0 mid-speech cuts)
    6. Broadcast pacing solver (DP break selection)
    7. Emits structured PipelineResult
    """
    cfg = config or PipelineConfig()

    # Step 1: Probe video
    metadata = probe_video(video_path)

    # Step 2: Demux audio
    audio_path, has_audio = extract_audio(video_path)
    metadata.has_audio = has_audio
    metadata.audio_path = audio_path

    # Step 3: Visual scene detection & refinement
    scenes, candidate_breaks = detect_and_refine_scenes(
        video_path=video_path,
        fps=metadata.fps,
        total_frames=metadata.frame_count,
        config=cfg,
    )

    # Step 4: Speech activity detection
    speech_intervals: List[SpeechInterval] = []
    if has_audio and audio_path and os.path.exists(audio_path):
        speech_intervals = detect_speech_intervals(audio_path)

    # Step 5: VAD silence window safety gating
    candidate_breaks = evaluate_breaks_vad_safety(
        candidate_breaks=candidate_breaks,
        speech_intervals=speech_intervals,
        safety_window_n=cfg.safety_window_seconds,
    )

    # Step 6: Pacing solver
    candidates_with_pacing, scheduled_breaks = solve_pacing(
        candidate_breaks=candidate_breaks,
        video_duration=metadata.duration,
        config=cfg,
    )

    return PipelineResult(
        video_metadata=metadata,
        scenes=scenes,
        speech_intervals=speech_intervals,
        candidate_breaks=candidates_with_pacing,
        scheduled_breaks=scheduled_breaks,
        config=cfg,
    )
