"""Generates synthetic playable MP4 commercial ad creatives for mock ad server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple

import cv2
import numpy as np

STATIC_ADS_DIR = Path(__file__).resolve().parent.parent / "static" / "ads"

BRAND_CREATIVES: Dict[str, Tuple[str, str, Tuple[int, int, int]]] = {
    "apex_athletics.mp4": (
        "Apex Athletics",
        "Performance Sportswear & Fitness",
        (180, 120, 20),  # BGR Cyan/Blue
    ),
    "aura_sparkling.mp4": (
        "Aura Sparkling Water",
        "Pure Hydration & Natural Wellness",
        (80, 180, 60),  # BGR Emerald Green
    ),
    "zenith_motors.mp4": (
        "Zenith Motors",
        "Next-Gen Electric Performance",
        (180, 80, 20),  # BGR Electric Blue
    ),
    "nova_cloud.mp4": (
        "Nova Cloud Systems",
        "Autonomous Cloud Architecture",
        (180, 50, 140),  # BGR Tech Purple
    ),
    "haven_financial.mp4": (
        "Haven Wealth & Trust",
        "Private Banking & Generational Wealth",
        (30, 150, 200),  # BGR Gold/Amber
    ),
    "luxe_escapes.mp4": (
        "Luxe Escapes",
        "World-Class Five-Star Resorts",
        (40, 100, 220),  # BGR Coral/Orange
    ),
    "glow_naturals.mp4": (
        "Glow Naturals",
        "Bioactive Organic Skincare",
        (140, 80, 210),  # BGR Rose Pink
    ),
    "culinary_craft.mp4": (
        "Culinary Craft",
        "Artisan Meal Kits & Gourmet Chef Dining",
        (30, 50, 170),  # BGR Warm Crimson
    ),
    "cyber_shield.mp4": (
        "CyberShield Defense",
        "Zero-Trust Cloud & Enterprise Protection",
        (160, 160, 30),  # BGR Teal/Cyan
    ),
    "sample.mp4": (
        "Cutaway Ad Creative",
        "Context-Aware Video Ad Placement",
        (90, 90, 90),  # BGR Neutral Slate
    ),
}


def create_ad_mp4(
    output_path: Path,
    brand_name: str,
    tagline: str,
    bg_color_bgr: Tuple[int, int, int],
    duration_seconds: float = 2.0,
    fps: float = 30.0,
    width: int = 640,
    height: int = 360,
) -> None:
    """Generates a small valid playable MP4 video file with animated countdown and branding."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(round(duration_seconds * fps))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    if not out.isOpened():
        raise RuntimeError(f"Could not open VideoWriter for {output_path}")

    for frame_idx in range(total_frames):
        # Background gradient effect
        t = frame_idx / max(1, total_frames - 1)
        base_b, base_g, base_r = bg_color_bgr
        dim_factor = 0.75 + 0.25 * np.sin(t * np.pi)

        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Fill with ambient color
        frame[:] = (
            int(base_b * dim_factor),
            int(base_g * dim_factor),
            int(base_r * dim_factor),
        )

        # Border
        cv2.rectangle(frame, (10, 10), (width - 10, height - 10), (255, 255, 255), 2)

        # "COMMERCIAL BREAK" banner
        cv2.putText(
            frame,
            "COMMERCIAL BREAK",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (200, 200, 200),
            1,
            cv2.LINE_AA,
        )

        # Brand Title
        cv2.putText(
            frame,
            brand_name,
            (30, 140),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.1,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

        # Tagline / Subtitle
        cv2.putText(
            frame,
            tagline,
            (30, 185),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )

        # Progress bar at bottom
        bar_y = height - 40
        bar_w = width - 60
        filled_w = int(bar_w * t)
        cv2.rectangle(frame, (30, bar_y), (30 + bar_w, bar_y + 12), (50, 50, 50), -1)
        if filled_w > 0:
            cv2.rectangle(frame, (30, bar_y), (30 + filled_w, bar_y + 12), (255, 255, 255), -1)

        # Countdown label
        time_left = max(0.0, duration_seconds * (1.0 - t))
        cv2.putText(
            frame,
            f"Ad will finish in {time_left:.1f}s",
            (30, bar_y - 12),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )

        out.write(frame)

    out.release()


PRESET_VIDEOS_DIR = Path(__file__).resolve().parent.parent / "static" / "sample_videos"

DEMO_PRESETS: Dict[str, Dict[str, Any]] = {
    "tech_review": {
        "id": "tech_review",
        "name": "Cloud Architecture & Cyber Defense",
        "category": "Enterprise Technology",
        "filename": "tech_review.mp4",
        "description": "Engineers collaborating on modern enterprise software and cloud infrastructure.",
        "duration": 6.0,
        "recommended_brands": ["nova_cloud", "cyber_shield"],
        "default_config": {
            "safety_window_seconds": 0.5,
            "min_gap_seconds": 1.0,
            "min_start_buffer_seconds": 0.5,
            "min_end_buffer_seconds": 0.5,
            "max_breaks_per_hour": 10.0,
            "ad_load_pct": 20.0,
        },
    },
    "sports_adventure": {
        "id": "sports_adventure",
        "name": "Seaside Sunrise Jogging & Athletic Sprint",
        "category": "Sports & Fitness",
        "filename": "sports_adventure.mp4",
        "description": "Outdoor endurance runners along seaside boardwalk with scenic sunrise vistas.",
        "duration": 6.0,
        "recommended_brands": ["apex_athletics", "aura_sparkling_water"],
        "default_config": {
            "safety_window_seconds": 0.5,
            "min_gap_seconds": 1.0,
            "min_start_buffer_seconds": 0.5,
            "min_end_buffer_seconds": 0.5,
            "max_breaks_per_hour": 10.0,
            "ad_load_pct": 20.0,
        },
    },
    "gourmet_kitchen": {
        "id": "gourmet_kitchen",
        "name": "Master Chef Artisan Pasta & Dining",
        "category": "Culinary & Dining",
        "filename": "gourmet_kitchen.mp4",
        "description": "Executive chef preparing farm-fresh organic pasta and fresh vegetables in a gourmet kitchen.",
        "duration": 6.0,
        "recommended_brands": ["culinary_craft", "aura_sparkling_water"],
        "default_config": {
            "safety_window_seconds": 0.5,
            "min_gap_seconds": 1.0,
            "min_start_buffer_seconds": 0.5,
            "min_end_buffer_seconds": 0.5,
            "max_breaks_per_hour": 10.0,
            "ad_load_pct": 20.0,
        },
    },
    "action_thriller": {
        "id": "action_thriller",
        "name": "High-Speed Pursuit & Critical Hazard",
        "category": "Action & Suspense",
        "filename": "action_thriller.mp4",
        "description": "Tense urban vehicle pursuit and dramatic hazard scene (demonstrates hard safety gating).",
        "duration": 6.0,
        "recommended_brands": [],
        "default_config": {
            "safety_window_seconds": 0.5,
            "min_gap_seconds": 1.0,
            "min_start_buffer_seconds": 0.5,
            "min_end_buffer_seconds": 0.5,
            "max_breaks_per_hour": 10.0,
            "ad_load_pct": 20.0,
        },
    },
}


def create_preset_video(
    output_path: Path,
    preset_id: str,
    duration_seconds: float = 6.0,
    fps: float = 30.0,
    width: int = 640,
    height: int = 360,
) -> None:
    """Creates a multi-scene demo video clip with sharp visual cuts."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(round(duration_seconds * fps))

    # 3 distinct scenes: 0-2s, 2-4s, 4-6s
    scene_frames = total_frames // 3
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    colors = [
        (40, 40, 160),   # Scene 1
        (40, 160, 40),   # Scene 2
        (160, 60, 40),   # Scene 3
    ]

    preset_info = DEMO_PRESETS.get(preset_id, {"name": preset_id, "category": "Demo"})

    for i in range(total_frames):
        scene_idx = min(2, i // scene_frames)
        bg = colors[scene_idx]
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = bg

        # Overlay text
        cv2.putText(
            frame,
            f"{preset_info['name']} - Scene {scene_idx + 1}",
            (30, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        time_sec = i / fps
        cv2.putText(
            frame,
            f"Timecode: {time_sec:05.2f}s / {duration_seconds:05.2f}s",
            (30, 140),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )

        out.write(frame)

    out.release()


def ensure_static_ads(target_dir: Path = STATIC_ADS_DIR) -> Dict[str, Path]:
    """Ensures all 10 ad creatives exist in the static ads directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    generated = {}
    for filename, (name, tagline, color) in BRAND_CREATIVES.items():
        file_path = target_dir / filename
        if not file_path.exists() or file_path.stat().st_size == 0:
            create_ad_mp4(file_path, name, tagline, color)
        generated[filename] = file_path
    return generated


def ensure_demo_presets(target_dir: Path = PRESET_VIDEOS_DIR) -> Dict[str, Path]:
    """Ensures all 4 preset videos exist."""
    target_dir.mkdir(parents=True, exist_ok=True)
    generated = {}
    for preset_id, meta in DEMO_PRESETS.items():
        file_path = target_dir / meta["filename"]
        if not file_path.exists() or file_path.stat().st_size == 0:
            create_preset_video(file_path, preset_id, duration_seconds=meta["duration"])
        generated[preset_id] = file_path
    return generated


if __name__ == "__main__":
    ads = ensure_static_ads()
    print(f"Generated {len(ads)} ad creatives in {STATIC_ADS_DIR}")
    presets = ensure_demo_presets()
    print(f"Generated {len(presets)} preset videos in {PRESET_VIDEOS_DIR}")

