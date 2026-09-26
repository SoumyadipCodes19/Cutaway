from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class SceneBoundary(BaseModel):
    scene_id: int
    start_time: float
    end_time: float
    start_frame: int
    end_frame: int
    transition_type: str = "cut"
    confidence: float = 1.0


class SpeechInterval(BaseModel):
    start_time: float
    end_time: float
    confidence: float = 1.0


class CandidateBreak(BaseModel):
    break_id: str
    cut_time: float
    lead_in_scene_id: int
    lead_out_scene_id: int
    vad_safe: bool
    nearest_speech_gap: float
    pacing_valid: bool
    status: str  # "CANDIDATE", "REJECTED_VAD", "REJECTED_PACING"
    rejection_reason: Optional[str] = None
    confidence: Optional[float] = 1.0


class VideoMetadata(BaseModel):
    duration: float
    fps: float
    frame_count: int
    width: int
    height: int
    has_audio: bool = True
    audio_sample_rate: Optional[int] = 16000
    audio_path: Optional[str] = None


class PipelineConfig(BaseModel):
    safety_window_seconds: float = Field(
        default=0.5,
        description="Half-width N of the silence safety window around cuts (in seconds).",
        ge=0.1,
        le=5.0,
    )
    min_start_buffer_seconds: float = Field(
        default=60.0,
        description="Minimum seconds from video start before first ad break.",
        ge=0.0,
    )
    min_end_buffer_seconds: float = Field(
        default=60.0,
        description="Minimum seconds before video end where ad breaks are disallowed.",
        ge=0.0,
    )
    min_gap_seconds: float = Field(
        default=120.0,
        description="Minimum spacing in seconds between consecutive ad breaks.",
        ge=1.0,
    )
    max_breaks_per_hour: float = Field(
        default=4.0,
        description="Maximum number of commercial breaks allowed per hour.",
        ge=1.0,
    )
    ad_load_pct: float = Field(
        default=10.0,
        description="Maximum commercial ad load percentage of total runtime.",
        ge=1.0,
        le=50.0,
    )
    ad_duration_seconds: float = Field(
        default=30.0,
        description="Assumed commercial pod duration in seconds for ad load solver.",
        ge=5.0,
    )
    coarse_threshold: float = Field(
        default=15.0,
        description="PySceneDetect ContentDetector threshold.",
    )
    min_scene_len_frames: int = Field(
        default=15,
        description="Minimum scene length in frames for coarse detector.",
    )
    transnet_threshold: float = Field(
        default=0.45,
        description="TransNetV2 cut probability threshold.",
    )


class PipelineResult(BaseModel):
    video_metadata: VideoMetadata
    scenes: List[SceneBoundary]
    speech_intervals: List[SpeechInterval]
    candidate_breaks: List[CandidateBreak]
    scheduled_breaks: List[CandidateBreak]
    config: PipelineConfig
