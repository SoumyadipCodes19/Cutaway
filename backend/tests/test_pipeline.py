"""Unit tests for Cutaway Milestone 1: Media Ingest, Scene Detection, Silero VAD, and Pacing.

Covers:
- F1: Media Ingest & Audio Demuxing (ffmpeg / probe / keyframe)
- F2: Coarse Scene Segmentation (PySceneDetect ContentDetector)
- F3: Fine Scene Refinement (TransNetV2 localized 100-frame window)
- F4: Silero VAD Speech Detection (speech interval extraction & audio tensor processing)
- F5: Silence Window Safety Gating (±N second window, 0 mid-speech cuts guarantee)
- F6: Broadcast Pacing Rules Solver (min gap, edge buffers, frequency cap, DP selection)
- Full Pipeline Orchestrator (run_pipeline end-to-end integration)
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from typing import Generator, List, Tuple

import cv2
import numpy as np
import pytest
import soundfile as sf
import torch

from backend.models.pipeline_models import (
    CandidateBreak,
    PipelineConfig,
    PipelineResult,
    SceneBoundary,
    SpeechInterval,
    VideoMetadata,
)
from backend.pipeline.ingest import (
    extract_audio,
    extract_keyframe,
    get_ffmpeg_binary,
    probe_video,
)
from backend.pipeline.pacing import (
    compute_break_quota,
    solve_pacing,
)
from backend.pipeline.scene_detector import (
    detect_and_refine_scenes,
    detect_scenes_coarse,
    get_transnet_model,
    refine_cut_with_transnet,
)
from backend.pipeline.vad_engine import (
    _energy_vad,
    detect_speech_intervals,
    evaluate_breaks_vad_safety,
    evaluate_silence_window,
    load_audio_tensor,
    load_silero_vad,
    run_pipeline,
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def test_temp_dir() -> Generator[str, None, None]:
    """Provides a dedicated temporary directory for test media artifacts."""
    d = tempfile.mkdtemp(prefix="cutaway_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def synthetic_video_with_cuts(test_temp_dir: str) -> str:
    """
    Generates a 4-second 30fps synthetic video (120 frames) with two sharp scene cuts:
    - Scene 1: Frames 0..39 (black)  [0.0s - 1.33s]
    - Scene 2: Frames 40..79 (white) [1.33s - 2.67s]
    - Scene 3: Frames 80..119 (gray) [2.67s - 4.00s]
    """
    video_path = os.path.join(test_temp_dir, "synthetic_cuts.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, 30.0, (320, 240))
    for i in range(120):
        if i < 40:
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
        elif i < 80:
            frame = np.ones((240, 320, 3), dtype=np.uint8) * 255
        else:
            frame = np.ones((240, 320, 3), dtype=np.uint8) * 128
        out.write(frame)
    out.release()
    return video_path


@pytest.fixture
def synthetic_video_single_scene(test_temp_dir: str) -> str:
    """Generates a 2-second 30fps single continuous scene video."""
    video_path = os.path.join(test_temp_dir, "synthetic_single.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(video_path, fourcc, 30.0, (320, 240))
    for _ in range(60):
        frame = np.ones((240, 320, 3), dtype=np.uint8) * 100
        out.write(frame)
    out.release()
    return video_path


@pytest.fixture
def synthetic_video_with_audio(test_temp_dir: str) -> str:
    """
    Generates a 6-second video with an active audio stream using ffmpeg:
    - Video testsrc (30fps)
    - Audio sine tone at 440Hz
    """
    video_path = os.path.join(test_temp_dir, "synthetic_with_audio.mp4")
    ffmpeg = get_ffmpeg_binary()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=6:size=320x240:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=6",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-pix_fmt",
        "yuv420p",
        video_path,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return video_path


@pytest.fixture
def synthetic_speech_wav(test_temp_dir: str) -> str:
    """
    Generates a 10-second 16kHz WAV audio file with two speech bursts:
    - Burst 1: [1.0s, 4.0s] (modulated harmonic vocal tones)
    - Silence: [4.0s, 6.0s]
    - Burst 2: [6.0s, 9.0s] (modulated harmonic vocal tones)
    - Silence: [9.0s, 10.0s]
    """
    wav_path = os.path.join(test_temp_dir, "speech_bursts.wav")
    sr = 16000
    duration = 10.0
    total_samples = int(duration * sr)
    audio = np.zeros(total_samples, dtype=np.float32)
    t = np.linspace(0, duration, total_samples, endpoint=False, dtype=np.float32)

    speech_ranges = [(1.0, 4.0), (6.0, 9.0)]
    for s_start, s_end in speech_ranges:
        idx_s = int(s_start * sr)
        idx_e = int(s_end * sr)
        t_seg = t[idx_s:idx_e]
        mod = 0.5 * (1.0 + np.sin(2.0 * np.pi * 4.0 * t_seg))
        signal = (
            0.6 * np.sin(2.0 * np.pi * 150.0 * t_seg)
            + 0.3 * np.sin(2.0 * np.pi * 300.0 * t_seg)
            + 0.1 * np.sin(2.0 * np.pi * 600.0 * t_seg)
        ) * mod
        audio[idx_s:idx_e] = signal.astype(np.float32)

    # Normalize to -0.95 .. 0.95
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = (audio / max_val) * 0.95

    sf.write(wav_path, audio, sr, subtype="PCM_16")
    return wav_path


@pytest.fixture
def pure_silence_wav(test_temp_dir: str) -> str:
    """Generates a 5-second 16kHz purely silent WAV file."""
    wav_path = os.path.join(test_temp_dir, "silence.wav")
    sr = 16000
    audio = np.zeros(sr * 5, dtype=np.float32)
    sf.write(wav_path, audio, sr, subtype="PCM_16")
    return wav_path


# ============================================================================
# F1: Media Ingest & Audio Demuxing Tests
# ============================================================================

class TestF1MediaIngest:
    """F1: Ingest arbitrary MP4, probe metadata, demux 16kHz mono audio via ffmpeg."""

    def test_f1_01_ffmpeg_binary_resolution(self):
        """Validates that ffmpeg binary is found and directory injected into PATH."""
        ffmpeg_exe = get_ffmpeg_binary()
        assert os.path.exists(ffmpeg_exe), f"ffmpeg executable not found at {ffmpeg_exe}"
        assert "ffmpeg" in os.path.basename(ffmpeg_exe).lower()

    def test_f1_02_probe_video_metadata(self, synthetic_video_with_cuts: str):
        """Validates extracting duration, fps, frame count, width, height from MP4."""
        meta = probe_video(synthetic_video_with_cuts)
        assert isinstance(meta, VideoMetadata)
        assert meta.fps == 30.0
        assert meta.frame_count == 120
        assert pytest.approx(meta.duration, 0.05) == 4.0
        assert meta.width == 320
        assert meta.height == 240
        assert meta.has_audio is False

    def test_f1_03_probe_video_with_audio_track(self, synthetic_video_with_audio: str):
        """Validates detection of audio stream capability on video containing audio."""
        meta = probe_video(synthetic_video_with_audio)
        assert meta.has_audio is True
        assert meta.duration >= 5.9

    def test_f1_04_probe_nonexistent_file_raises_error(self):
        """Validates proper FileNotFoundError when probing non-existent video path."""
        with pytest.raises(FileNotFoundError):
            probe_video("c:/non_existent_video_path.mp4")

    def test_f1_05_extract_audio_pcm16_mono(self, synthetic_video_with_audio: str, test_temp_dir: str):
        """Validates demuxing audio into 16kHz mono 16-bit PCM WAV."""
        out_wav = os.path.join(test_temp_dir, "extracted_audio.wav")
        wav_path, has_audio = extract_audio(synthetic_video_with_audio, output_wav_path=out_wav)
        assert has_audio is True
        assert wav_path is not None
        assert os.path.exists(wav_path)

        data, sr = sf.read(wav_path)
        assert sr == 16000
        assert data.ndim == 1  # Mono
        assert len(data) > 0

    def test_f1_06_extract_audio_silent_video_graceful(self, synthetic_video_with_cuts: str):
        """Validates graceful handling of video with no audio track without exception."""
        wav_path, has_audio = extract_audio(synthetic_video_with_cuts)
        assert has_audio is False
        assert wav_path is None

    def test_f1_07_extract_keyframe(self, synthetic_video_with_cuts: str, test_temp_dir: str):
        """Validates extracting and saving a keyframe image at timestamp."""
        kf_path = os.path.join(test_temp_dir, "keyframe_01.jpg")
        success = extract_keyframe(synthetic_video_with_cuts, timestamp_sec=1.0, output_image_path=kf_path)
        assert success is True
        assert os.path.exists(kf_path)
        assert os.path.getsize(kf_path) > 500


# ============================================================================
# F2: Coarse Scene Segmentation Tests
# ============================================================================

class TestF2CoarseSceneSegmentation:
    """F2: Coarse visual cut candidate detection on CPU using PySceneDetect."""

    def test_f2_01_detect_scenes_coarse_finds_cuts(self, synthetic_video_with_cuts: str):
        """Validates that PySceneDetect ContentDetector identifies scene transitions."""
        cfg = PipelineConfig(coarse_threshold=20.0, min_scene_len_frames=15)
        scenes = detect_scenes_coarse(synthetic_video_with_cuts, cfg)
        # 3 scenes means 3 boundary tuples: (0..40), (40..80), (80..120)
        assert len(scenes) >= 2
        # Verify first scene starts at 0
        assert scenes[0][0] == 0
        # Verify monotonic timestamps
        for i in range(len(scenes) - 1):
            assert scenes[i][1] <= scenes[i + 1][0] or scenes[i][1] == scenes[i + 1][0]

    def test_f2_02_detect_scenes_coarse_single_scene(self, synthetic_video_single_scene: str):
        """Validates that a video without visual cuts returns a single scene boundary."""
        cfg = PipelineConfig(coarse_threshold=27.0, min_scene_len_frames=15)
        scenes = detect_scenes_coarse(synthetic_video_single_scene, cfg)
        assert len(scenes) == 1
        assert scenes[0][0] == 0
        assert scenes[0][1] == 60


# ============================================================================
# F3: Fine Scene Refinement Tests
# ============================================================================

class TestF3FineSceneRefinement:
    """F3: Refine candidate cuts to frame accuracy using TransNetV2 in 100-frame window."""

    def test_f3_01_transnet_model_loader(self):
        """Validates TransNetV2 model loading and singleton caching."""
        model = get_transnet_model()
        assert model is not None
        assert model is get_transnet_model()  # Singleton check

    def test_f3_02_refine_cut_with_transnet(self, synthetic_video_with_cuts: str):
        """Validates local 100-frame window refinement around coarse cut point."""
        refined_frame, refined_time, conf = refine_cut_with_transnet(
            video_path=synthetic_video_with_cuts,
            approx_frame=40,
            total_frames=120,
            fps=30.0,
            threshold=0.40,
        )
        assert 35 <= refined_frame <= 45
        assert pytest.approx(refined_time, 0.2) == (refined_frame / 30.0)
        assert conf > 0.40

    def test_f3_03_detect_and_refine_scenes_boundaries(self, synthetic_video_with_cuts: str):
        """Validates complete two-stage detection produces contiguous, non-overlapping SceneBoundary list."""
        cfg = PipelineConfig(coarse_threshold=20.0, transnet_threshold=0.40)
        scenes, breaks = detect_and_refine_scenes(synthetic_video_with_cuts, fps=30.0, total_frames=120, config=cfg)
        assert len(scenes) >= 2
        assert len(breaks) == len(scenes) - 1

        # Check contiguous non-overlapping scenes
        assert scenes[0].start_frame == 0
        assert pytest.approx(scenes[0].start_time, 0.01) == 0.0
        for i in range(len(scenes) - 1):
            assert scenes[i].end_frame == scenes[i + 1].start_frame
            assert scenes[i].end_time == scenes[i + 1].start_time
            assert breaks[i].cut_time == pytest.approx(scenes[i].end_time, 0.01)
            assert breaks[i].lead_in_scene_id == scenes[i].scene_id
            assert breaks[i].lead_out_scene_id == scenes[i + 1].scene_id

    def test_f3_04_single_scene_produces_zero_breaks(self, synthetic_video_single_scene: str):
        """Validates that a single continuous scene video produces 0 candidate breaks."""
        cfg = PipelineConfig()
        scenes, breaks = detect_and_refine_scenes(synthetic_video_single_scene, fps=30.0, total_frames=60, config=cfg)
        assert len(scenes) == 1
        assert len(breaks) == 0


# ============================================================================
# F4: Silero VAD Speech Detection Tests
# ============================================================================

class TestF4SileroVADSpeechDetection:
    """F4: Silero VAD Speech Detection and Speech Interval Extraction."""

    def test_f4_01_silero_vad_model_loads(self):
        """Validates loading Silero VAD on CPU."""
        model, utils = load_silero_vad(onnx=True)
        assert model is not None
        assert utils is not None
        assert callable(utils[0])  # get_speech_timestamps

    def test_f4_02_detect_speech_intervals_synthetic_bursts(self, synthetic_speech_wav: str):
        """Validates detection of speech bursts in synthetic audio."""
        intervals = detect_speech_intervals(synthetic_speech_wav)
        assert len(intervals) >= 2
        # First burst was [1.0s, 4.0s]
        assert any(abs(it.start_time - 1.0) < 0.5 and abs(it.end_time - 4.0) < 0.5 for it in intervals)
        # Second burst was [6.0s, 9.0s]
        assert any(abs(it.start_time - 6.0) < 0.5 and abs(it.end_time - 9.0) < 0.5 for it in intervals)

    def test_f4_03_detect_speech_intervals_pure_silence(self, pure_silence_wav: str):
        """Validates that purely silent audio yields zero speech intervals."""
        intervals = detect_speech_intervals(pure_silence_wav)
        assert len(intervals) == 0

    def test_f4_04_speech_interval_ordering_and_positivity(self, synthetic_speech_wav: str):
        """Validates strict invariant start_time < end_time on all speech intervals."""
        intervals = detect_speech_intervals(synthetic_speech_wav)
        for it in intervals:
            assert isinstance(it, SpeechInterval)
            assert it.start_time < it.end_time
            assert it.start_time >= 0.0
            assert it.confidence > 0.0

    def test_f4_05_load_audio_tensor_downmixing_and_resampling(self):
        """Validates multichannel downmixing to mono and resampling to 16kHz."""
        # Create 48kHz stereo numpy array
        sr_48k = 48000
        t = np.linspace(0, 1.0, sr_48k, endpoint=False)
        ch1 = np.sin(2 * np.pi * 440 * t)
        ch2 = np.sin(2 * np.pi * 880 * t)
        stereo_48k = np.stack([ch1, ch2], axis=-1)

        tensor, target_sr = load_audio_tensor(stereo_48k, target_sr=16000, source_sr=sr_48k)
        assert target_sr == 16000
        assert tensor.ndim == 1
        assert tensor.shape[0] == 16000
        assert tensor.dtype == torch.float32

    def test_f4_06_energy_vad_fallback(self):
        """Validates genuine energy-based VAD fallback logic."""
        sr = 16000
        # 4-second audio: 1s silence, 2s active noise/tone, 1s silence
        t = np.linspace(0, 4.0, 4 * sr, endpoint=False)
        audio = np.zeros(4 * sr, dtype=np.float32)
        audio[sr : 3 * sr] = 0.5 * np.sin(2 * np.pi * 300 * t[sr : 3 * sr])

        intervals = _energy_vad(audio, sample_rate=sr, energy_threshold=0.05)
        assert len(intervals) == 1
        assert pytest.approx(intervals[0].start_time, 0.1) == 1.0
        assert pytest.approx(intervals[0].end_time, 0.1) == 3.0


# ============================================================================
# F5: Silence Window Safety Gating Tests (AC-Where: 0 mid-speech cuts)
# ============================================================================

class TestF5SilenceWindowSafetyGating:
    """F5: Silence Window Safety Gating (AC-Where: 0 mid-speech cuts)."""

    def test_f5_01_safety_window_passes_when_clear(self):
        """Validates candidate cut is accepted when ±0.5s window has no speech."""
        speech = [(1.0, 3.0), (7.0, 10.0)]
        res = evaluate_silence_window(cut_time=5.0, speech_intervals=speech, safety_window_n=0.5)
        assert res["vad_safe"] is True
        assert res["status"] == "CANDIDATE"
        assert res["safety_margin_violated"] == 0.0
        assert res["nearest_speech_gap"] >= 2.0
        assert res["safety_window"] == (4.5, 5.5)

    def test_f5_02_safety_window_rejects_speech_overlap(self):
        """Validates candidate cut is rejected when speech overlaps ±0.5s window."""
        speech = [(2.0, 4.0)]
        # Cut at 4.2s has window [3.7, 4.7], which overlaps speech [2.0, 4.0]
        res = evaluate_silence_window(cut_time=4.2, speech_intervals=speech, safety_window_n=0.5)
        assert res["vad_safe"] is False
        assert res["status"] == "REJECTED_SPEECH_OVERLAP"
        assert res["safety_margin_violated"] > 0.0
        assert res["overlapping_speech"] == (2.0, 4.0)

    def test_f5_03_zero_mid_speech_cuts_guarantee(self):
        """AC-Where: Asserts that 0 mid-speech cuts occur across all accepted breaks."""
        speech = [(10.0, 20.0), (30.0, 40.0), (50.0, 60.0)]
        candidates = [15.0, 25.0, 35.0, 45.0, 55.0]  # 15, 35, 55 are mid-speech; 25, 45 are safe
        accepted = []
        for c in candidates:
            eval_res = evaluate_silence_window(cut_time=c, speech_intervals=speech, safety_window_n=0.5)
            if eval_res["vad_safe"]:
                accepted.append(c)

        assert accepted == [25.0, 45.0]
        # Strict invariant verification: None of the accepted cuts fall inside any speech interval
        for acc in accepted:
            for s, e in speech:
                assert not (s <= acc <= e), f"Cut {acc} violated mid-speech invariant"

    def test_f5_04_nearest_speech_gap_calculation(self):
        """Validates accurate distance calculation to nearest speech boundary."""
        speech = [(1.0, 3.0), (8.0, 10.0)]
        res = evaluate_silence_window(cut_time=5.0, speech_intervals=speech, safety_window_n=0.5)
        # distance to prev speech end (3.0) is 2.0; to next speech start (8.0) is 3.0 -> min gap is 2.0
        assert pytest.approx(res["nearest_speech_gap"], 0.01) == 2.0

    def test_f5_05_configurable_safety_window_n(self):
        """Validates safety window tolerance scales with configurable N parameter."""
        speech = [(1.0, 3.0), (4.5, 6.0)]
        # Cut at 3.8s: distance to prev speech is 0.8s, to next is 0.7s
        # If N = 0.5s: safe
        res_05 = evaluate_silence_window(cut_time=3.8, speech_intervals=speech, safety_window_n=0.5)
        assert res_05["vad_safe"] is True
        # If N = 1.0s: window [2.8, 4.8] overlaps both speech intervals -> rejected
        res_10 = evaluate_silence_window(cut_time=3.8, speech_intervals=speech, safety_window_n=1.0)
        assert res_10["vad_safe"] is False

    def test_f5_06_evaluate_breaks_vad_safety_updates_models(self):
        """Validates evaluate_breaks_vad_safety updates CandidateBreak list."""
        breaks = [
            CandidateBreak(
                break_id="break_001",
                cut_time=5.0,
                lead_in_scene_id=1,
                lead_out_scene_id=2,
                vad_safe=False,
                nearest_speech_gap=0.0,
                pacing_valid=False,
                status="CANDIDATE",
            ),
            CandidateBreak(
                break_id="break_002",
                cut_time=12.0,
                lead_in_scene_id=2,
                lead_out_scene_id=3,
                vad_safe=False,
                nearest_speech_gap=0.0,
                pacing_valid=False,
                status="CANDIDATE",
            ),
        ]
        speech = [SpeechInterval(start_time=11.8, end_time=14.0, confidence=1.0)]

        updated = evaluate_breaks_vad_safety(breaks, speech, safety_window_n=0.5)
        assert updated[0].vad_safe is True
        assert updated[0].status == "CANDIDATE"
        assert updated[0].nearest_speech_gap >= 6.0

        assert updated[1].vad_safe is False
        assert updated[1].status == "REJECTED_VAD"
        assert "REJECTED_SPEECH_OVERLAP" in updated[1].rejection_reason


# ============================================================================
# F6: Pacing Rules Solver Tests (AC-Whether)
# ============================================================================

class TestF6PacingRulesSolver:
    """F6: Pacing Rules Solver (AC-Whether)."""

    def test_f6_01_compute_break_quota(self):
        """Validates break quota computation based on duration, rate limit, and ad load."""
        cfg = PipelineConfig(
            max_breaks_per_hour=4.0,
            ad_load_pct=10.0,
            ad_duration_seconds=30.0,
            min_start_buffer_seconds=60.0,
            min_end_buffer_seconds=60.0,
            min_gap_seconds=120.0,
        )
        # 1-hour video (3600s):
        # rate_quota = floor(3600/3600 * 4) = 4
        # load_quota = floor((3600 * 0.10) / 30) = floor(360 / 30) = 12
        # quota = min(4, 12) = 4
        assert compute_break_quota(3600.0, cfg) == 4

        # Very short video (90s) with 60s start + 60s end buffer:
        # available runtime = 90 - 120 = -30s -> quota = 0
        assert compute_break_quota(90.0, cfg) == 0

    def test_f6_02_min_gap_seconds_enforcement(self):
        """AC-Whether: Validates that consecutive scheduled breaks respect min_gap_seconds."""
        candidate_times = [100.0, 150.0, 280.0, 310.0, 450.0]
        breaks = [
            CandidateBreak(
                break_id=f"b_{i}",
                cut_time=t,
                lead_in_scene_id=i,
                lead_out_scene_id=i + 1,
                vad_safe=True,
                nearest_speech_gap=5.0,
                pacing_valid=False,
                status="CANDIDATE",
            )
            for i, t in enumerate(candidate_times)
        ]
        cfg = PipelineConfig(
            min_gap_seconds=120.0,
            min_start_buffer_seconds=60.0,
            min_end_buffer_seconds=60.0,
            max_breaks_per_hour=10.0,
        )
        _, scheduled = solve_pacing(breaks, video_duration=600.0, config=cfg)
        for i in range(len(scheduled) - 1):
            gap = scheduled[i + 1].cut_time - scheduled[i].cut_time
            assert gap >= 120.0, f"Gap {gap} between breaks violates min_gap_seconds 120.0"

    def test_f6_03_buffer_zones_enforcement(self):
        """Validates cuts inside min_start_buffer and min_end_buffer are rejected."""
        breaks = [
            CandidateBreak(
                break_id="b_early",
                cut_time=30.0,  # inside 60s start buffer
                lead_in_scene_id=1,
                lead_out_scene_id=2,
                vad_safe=True,
                nearest_speech_gap=5.0,
                pacing_valid=False,
                status="CANDIDATE",
            ),
            CandidateBreak(
                break_id="b_valid",
                cut_time=300.0,
                lead_in_scene_id=2,
                lead_out_scene_id=3,
                vad_safe=True,
                nearest_speech_gap=5.0,
                pacing_valid=False,
                status="CANDIDATE",
            ),
            CandidateBreak(
                break_id="b_late",
                cut_time=580.0,  # inside 60s end buffer (video duration 600s)
                lead_in_scene_id=3,
                lead_out_scene_id=4,
                vad_safe=True,
                nearest_speech_gap=5.0,
                pacing_valid=False,
                status="CANDIDATE",
            ),
        ]
        cfg = PipelineConfig(
            min_start_buffer_seconds=60.0,
            min_end_buffer_seconds=60.0,
        )
        candidates, scheduled = solve_pacing(breaks, video_duration=600.0, config=cfg)
        assert len(scheduled) == 1
        assert scheduled[0].break_id == "b_valid"

        early_cand = next(c for c in candidates if c.break_id == "b_early")
        assert early_cand.status == "REJECTED_PACING"
        assert "REJECTED_EDGE_BUFFER" in early_cand.rejection_reason

        late_cand = next(c for c in candidates if c.break_id == "b_late")
        assert late_cand.status == "REJECTED_PACING"
        assert "REJECTED_EDGE_BUFFER" in late_cand.rejection_reason

    def test_f6_04_vad_rejected_candidates_remain_rejected(self):
        """Validates that candidate breaks rejected by VAD are never scheduled by pacing."""
        breaks = [
            CandidateBreak(
                break_id="b_unsafe",
                cut_time=200.0,
                lead_in_scene_id=1,
                lead_out_scene_id=2,
                vad_safe=False,
                nearest_speech_gap=0.0,
                pacing_valid=False,
                status="REJECTED_VAD",
                rejection_reason="REJECTED_SPEECH_OVERLAP",
            ),
            CandidateBreak(
                break_id="b_safe",
                cut_time=400.0,
                lead_in_scene_id=2,
                lead_out_scene_id=3,
                vad_safe=True,
                nearest_speech_gap=10.0,
                pacing_valid=False,
                status="CANDIDATE",
            ),
        ]
        cfg = PipelineConfig(min_gap_seconds=60.0)
        candidates, scheduled = solve_pacing(breaks, video_duration=600.0, config=cfg)
        assert len(scheduled) == 1
        assert scheduled[0].break_id == "b_safe"

        unsafe_cand = next(c for c in candidates if c.break_id == "b_unsafe")
        assert unsafe_cand.status == "REJECTED_VAD"
        assert unsafe_cand.pacing_valid is False


# ============================================================================
# Full Pipeline End-to-End Orchestrator Integration Test
# ============================================================================

class TestFullPipelineOrchestrator:
    """Full integration test for run_pipeline."""

    def test_full_pipeline_run_integration(self, synthetic_video_with_audio: str):
        """Validates end-to-end media pipeline run returning structured PipelineResult."""
        cfg = PipelineConfig(
            min_start_buffer_seconds=0.5,
            min_end_buffer_seconds=0.5,
            min_gap_seconds=1.0,
            coarse_threshold=20.0,
            safety_window_seconds=0.3,
        )
        result = run_pipeline(synthetic_video_with_audio, config=cfg)
        assert isinstance(result, PipelineResult)
        assert isinstance(result.video_metadata, VideoMetadata)
        assert result.video_metadata.duration >= 5.9
        assert result.video_metadata.has_audio is True
        assert len(result.scenes) >= 1
        assert isinstance(result.speech_intervals, list)
        assert isinstance(result.candidate_breaks, list)
        assert isinstance(result.scheduled_breaks, list)
        assert result.config.min_gap_seconds == 1.0
