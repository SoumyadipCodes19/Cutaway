from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np
import torch
from scenedetect import ContentDetector, SceneManager, open_video

from backend.models.pipeline_models import CandidateBreak, PipelineConfig, SceneBoundary

logger = logging.getLogger(__name__)

# Global singleton cache for TransNetV2 model to avoid re-instantiating heavy CNN
_TRANSNET_MODEL = None


def get_transnet_model():
    """Lazily loads and caches the TransNetV2 model."""
    global _TRANSNET_MODEL
    if _TRANSNET_MODEL is None:
        try:
            from transnetv2_pytorch import TransNetV2

            model = TransNetV2()
            model.eval()
            _TRANSNET_MODEL = model
            logger.info("TransNetV2 model loaded successfully.")
        except Exception as e:
            logger.warning("Could not initialize TransNetV2: %s", e)
            _TRANSNET_MODEL = False
    return _TRANSNET_MODEL if _TRANSNET_MODEL is not False else None


def detect_scenes_coarse(video_path: str, config: PipelineConfig) -> List[Tuple[int, int, float, float]]:
    """
    Executes PySceneDetect coarse scene boundary scan using ContentDetector.
    Returns: list of (start_frame, end_frame, start_time, end_time)
    """
    video = open_video(video_path)
    scene_manager = SceneManager()
    detector = ContentDetector(
        threshold=config.coarse_threshold,
        min_scene_len=config.min_scene_len_frames,
    )
    scene_manager.add_detector(detector)
    scene_manager.detect_scenes(video)
    scene_list = scene_manager.get_scene_list()

    coarse_scenes: List[Tuple[int, int, float, float]] = []
    if not scene_list:
        # Whole video as single scene
        cap = cv2.VideoCapture(video_path)
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        cap.release()
        duration = total_frames / fps if fps > 0 else 0.0
        return [(0, total_frames, 0.0, duration)]

    for start_tc, end_tc in scene_list:
        coarse_scenes.append(
            (
                int(start_tc.frame_num),
                int(end_tc.frame_num),
                float(start_tc.seconds),
                float(end_tc.seconds),
            )
        )
    return coarse_scenes


def refine_cut_with_transnet(
    video_path: str,
    approx_frame: int,
    total_frames: int,
    fps: float,
    threshold: float = 0.45,
) -> Tuple[int, float, float]:
    """
    Refines a coarse cut frame index using TransNetV2 in a 100-frame localized window.

    Returns:
        (refined_frame_idx, refined_timestamp_sec, confidence)
    """
    model = get_transnet_model()
    approx_time = approx_frame / fps if fps > 0 else 0.0
    if model is None:
        return approx_frame, approx_time, 0.85

    # Extract 100-frame window centered around approx_frame
    window_size = 100
    half_w = window_size // 2
    start_f = max(0, approx_frame - half_w)
    end_f = min(total_frames, start_f + window_size)
    if (end_f - start_f) < window_size:
        start_f = max(0, end_f - window_size)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return approx_frame, approx_time, 0.85

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
    frames = []
    try:
        for _ in range(window_size):
            ret, frame = cap.read()
            if not ret or frame is None:
                # Pad with black frame if EOF reached
                frame = np.zeros((27, 48, 3), dtype=np.uint8)
            else:
                # Resize to TransNetV2 input size (48, 27) and convert BGR -> RGB
                resized = cv2.resize(frame, (48, 27), interpolation=cv2.INTER_AREA)
                frame = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            frames.append(frame)
    finally:
        cap.release()

    if len(frames) != window_size:
        return approx_frame, approx_time, 0.85

    frames_arr = np.stack(frames, axis=0)  # (100, 27, 48, 3)
    frames_tensor = torch.from_numpy(frames_arr).unsqueeze(0).to(torch.uint8)  # (1, 100, 27, 48, 3)

    try:
        with torch.no_grad():
            single_frame_pred, _ = model.predict_raw(frames_tensor)
            probs = single_frame_pred[0, :, 0].cpu().numpy()

        peak_idx = int(np.argmax(probs))
        peak_prob = float(probs[peak_idx])

        if peak_prob >= threshold:
            refined_frame = start_f + peak_idx
            refined_time = refined_frame / fps if fps > 0 else 0.0
            return refined_frame, refined_time, peak_prob
        else:
            # Low confidence transition - retain coarse frame with moderate confidence
            return approx_frame, approx_time, max(0.5, peak_prob)
    except Exception as e:
        logger.warning("TransNetV2 inference error: %s", e)
        return approx_frame, approx_time, 0.80


def detect_and_refine_scenes(
    video_path: str,
    fps: float,
    total_frames: int,
    config: PipelineConfig,
) -> Tuple[List[SceneBoundary], List[CandidateBreak]]:
    """
    Two-stage coarse-to-fine visual scene segmentation pipeline:
    1. Coarse detection via PySceneDetect ContentDetector
    2. Local 100-frame window refinement via TransNetV2
    3. Output structured SceneBoundary list and CandidateBreak list
    """
    coarse_tuples = detect_scenes_coarse(video_path, config)

    if len(coarse_tuples) <= 1:
        # Single scene, no cuts
        s_f, e_f, s_t, e_t = coarse_tuples[0] if coarse_tuples else (0, total_frames, 0.0, total_frames / fps)
        scenes = [
            SceneBoundary(
                scene_id=1,
                start_time=s_t,
                end_time=e_t,
                start_frame=s_f,
                end_frame=e_f,
                transition_type="cut",
                confidence=1.0,
            )
        ]
        return scenes, []

    # Refine cuts between adjacent scenes
    refined_cuts: List[Tuple[int, float, float]] = []  # (frame, time, confidence)
    for i in range(len(coarse_tuples) - 1):
        _, end_frame_coarse, _, end_time_coarse = coarse_tuples[i]
        r_frame, r_time, r_conf = refine_cut_with_transnet(
            video_path=video_path,
            approx_frame=end_frame_coarse,
            total_frames=total_frames,
            fps=fps,
            threshold=config.transnet_threshold,
        )
        refined_cuts.append((r_frame, r_time, r_conf))

    # Reconstruct SceneBoundary list with frame-exact monotonic boundaries
    scenes: List[SceneBoundary] = []
    prev_frame = 0
    prev_time = 0.0

    for i, (cut_frame, cut_time, conf) in enumerate(refined_cuts):
        # Guarantee strictly ascending boundaries
        if cut_frame <= prev_frame:
            cut_frame = prev_frame + 1
            cut_time = cut_frame / fps if fps > 0 else prev_time + 0.04

        scene_id = i + 1
        scenes.append(
            SceneBoundary(
                scene_id=scene_id,
                start_time=prev_time,
                end_time=cut_time,
                start_frame=prev_frame,
                end_frame=cut_frame,
                transition_type="cut",
                confidence=conf,
            )
        )
        prev_frame = cut_frame
        prev_time = cut_time

    # Final scene
    final_frame = max(prev_frame + 1, total_frames)
    final_time = final_frame / fps if fps > 0 else prev_time + 1.0
    scenes.append(
        SceneBoundary(
            scene_id=len(scenes) + 1,
            start_time=prev_time,
            end_time=final_time,
            start_frame=prev_frame,
            end_frame=final_frame,
            transition_type="cut",
            confidence=1.0,
        )
    )

    # Build CandidateBreak list from transitions
    candidate_breaks: List[CandidateBreak] = []
    for i in range(len(scenes) - 1):
        lead_in = scenes[i]
        lead_out = scenes[i + 1]
        cut_time = lead_in.end_time
        break_id = f"break_{i + 1:03d}"
        candidate_breaks.append(
            CandidateBreak(
                break_id=break_id,
                cut_time=round(cut_time, 3),
                lead_in_scene_id=lead_in.scene_id,
                lead_out_scene_id=lead_out.scene_id,
                vad_safe=False,
                nearest_speech_gap=0.0,
                pacing_valid=False,
                status="CANDIDATE",
                confidence=lead_in.confidence,
            )
        )

    return scenes, candidate_breaks
