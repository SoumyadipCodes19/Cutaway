from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import cv2
from backend.models.pipeline_models import VideoMetadata


def get_ffmpeg_binary() -> str:
    """
    Finds the ffmpeg binary, checking:
    1. System PATH
    2. imageio-ffmpeg bundled binary
    Injects the binary's directory into os.environ['PATH'] so subprocesses find it.
    """
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg

    try:
        import imageio_ffmpeg

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(ffmpeg_exe)
        current_path = os.environ.get("PATH", "")
        if ffmpeg_dir not in current_path:
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + current_path
        return ffmpeg_exe
    except Exception as exc:
        raise RuntimeError(
            f"ffmpeg binary could not be resolved from PATH or imageio_ffmpeg: {exc}"
        ) from exc


def probe_video(video_path: str) -> VideoMetadata:
    """
    Probes video file using OpenCV and ffmpeg to determine duration,
    fps, frame count, dimensions, and audio stream presence.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found at {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Failed to open video file {video_path}")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()

    if fps <= 0:
        fps = 25.0
    duration = frame_count / fps if fps > 0 else 0.0

    # Probe audio track existence using ffmpeg
    ffmpeg_exe = get_ffmpeg_binary()
    probe_cmd = [ffmpeg_exe, "-nostdin", "-i", video_path]
    res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # ffmpeg prints stream info to stderr
    has_audio = "Audio:" in res.stderr

    return VideoMetadata(
        duration=duration,
        fps=fps,
        frame_count=frame_count,
        width=width,
        height=height,
        has_audio=has_audio,
        audio_sample_rate=16000 if has_audio else None,
        audio_path=None,
    )


def extract_audio(
    video_path: str,
    output_wav_path: Optional[str] = None,
) -> Tuple[Optional[str], bool]:
    """
    Demuxes and converts audio track from video to 16kHz mono 16-bit PCM WAV.
    Handles silent / audio-free videos gracefully without failing.

    Returns:
        (wav_path, has_audio)
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if output_wav_path is None:
        temp_dir = tempfile.gettempdir()
        base_name = Path(video_path).stem
        output_wav_path = os.path.join(temp_dir, f"{base_name}_16k_mono.wav")

    ffmpeg_exe = get_ffmpeg_binary()
    cmd = [
        ffmpeg_exe,
        "-y",
        "-nostdin",
        "-i",
        video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        output_wav_path,
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # Check if audio extraction was successful
    if result.returncode != 0 or not os.path.exists(output_wav_path):
        # Video is silent or has no audio track
        if os.path.exists(output_wav_path):
            try:
                os.remove(output_wav_path)
            except OSError:
                pass
        return None, False

    # Check if WAV file has more than just the header (> 44 bytes)
    file_size = os.path.getsize(output_wav_path)
    if file_size <= 44:
        try:
            os.remove(output_wav_path)
        except OSError:
            pass
        return None, False

    return output_wav_path, True


def extract_keyframe(video_path: str, timestamp_sec: float, output_image_path: str) -> bool:
    """
    Extracts a single keyframe at the specified timestamp in seconds and saves to disk.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False

    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp_sec * 1000.0))
        success, frame = cap.read()
        if success and frame is not None:
            cv2.imwrite(output_image_path, frame)
            return True
        return False
    finally:
        cap.release()
