"""Gemini API Scene Understanding Analyzer & Offline Deterministic Mock Fallback.

Extracts semantic scene understanding, sentiment, key objects, and 12-category GARM
brand safety tags from video scenes/keyframes using Google Gemini multimodal API,
with a robust deterministic mock analyzer fallback when GEMINI_API_KEY is unset or
network is unreachable.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import requests

from backend.models.brand_models import (
    ALL_GARM_TAGS,
    GARMSafetyTag,
    SceneUnderstanding,
    SentimentEnum,
)

logger = logging.getLogger(__name__)

GEMINI_PROMPT_TEMPLATE = """
You are Cutaway AI, an expert video content analyst and brand safety auditor adhering strictly to the Global Alliance for Responsible Media (GARM) Brand Safety & Suitability Framework.

Analyze the visual content of the provided scene keyframe(s).
Output a strictly valid JSON object matching this schema:
{
  "dominant_activity": "Detailed description of primary action taking place",
  "setting": "Physical location / environment",
  "sentiment": "One of ['positive', 'neutral', 'negative', 'uplifting', 'exciting', 'tense', 'sad']",
  "garm_safety_tags": ["subset of GARM safety categories or 'safe_all_audiences' if zero violations"],
  "contextual_tags": ["3 to 6 lowercase thematic topic tags for brand affinity"],
  "key_objects": ["notable visible physical objects"],
  "brand_suitability_summary": "1 concise sentence assessing advertising suitability"
}

Allowed GARM safety categories:
- adult_content
- arms_weapons
- crime_illegal
- death_injury
- hate_speech
- military_conflict
- obscenity_profanity
- substance_abuse
- tobacco_nicotine
- terrorism
- sensitive_social_issues
- safe_all_audiences (use ONLY when none of the above are present)

Respond strictly with valid JSON.
"""


class MockGeminiAnalyzer:
    """Deterministic offline scene analyzer simulating Gemini API responses.
    
    Guarantees deterministic scene understanding for offline development,
    CI/CD runs, and unit/integration testing without requiring API keys or network access.
    """

    # Pre-canned deterministic scene profiles indexed by scene_id
    DETERMINISTIC_SCENES: Dict[int, Dict[str, Any]] = {
        0: {
            "dominant_activity": "Two friends jogging along a seaside boardwalk at sunrise",
            "setting": "Sunny coastal path with ocean in background",
            "sentiment": SentimentEnum.UPLIFTING.value,
            "garm_safety_tags": [GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            "contextual_tags": ["fitness", "sports", "running", "healthy_living", "beverage"],
            "key_objects": ["running shoes", "water bottle", "smartwatch", "sunglasses"],
            "brand_suitability_summary": "Brand-safe outdoor fitness scene ideal for athletic wear and wellness.",
        },
        1: {
            "dominant_activity": "Chef skillfully preparing fresh organic pasta and vegetables in a kitchen",
            "setting": "Bright gourmet kitchen",
            "sentiment": SentimentEnum.POSITIVE.value,
            "garm_safety_tags": [GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            "contextual_tags": ["cooking", "chef", "gourmet", "kitchen", "dining", "food"],
            "key_objects": ["skillet", "chef knife", "olive oil", "bell peppers"],
            "brand_suitability_summary": "Brand-safe culinary scene ideal for food, meal kits, and cookware brands.",
        },
        2: {
            "dominant_activity": "Software engineers collaborating around dual monitors in modern tech workspace",
            "setting": "Contemporary open-plan software office",
            "sentiment": SentimentEnum.POSITIVE.value,
            "garm_safety_tags": [GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            "contextual_tags": ["technology", "business", "coding", "software", "collaboration", "cybersecurity"],
            "key_objects": ["laptops", "monitors", "whiteboard", "keyboard"],
            "brand_suitability_summary": "Brand-safe technology scene ideal for cloud SaaS and cybersecurity brands.",
        },
        3: {
            "dominant_activity": "Electric car driving along scenic coastal cliffside highway at golden hour",
            "setting": "Pacific coastal highway at dusk",
            "sentiment": SentimentEnum.POSITIVE.value,
            "garm_safety_tags": [GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            "contextual_tags": ["automotive", "driving", "luxury", "clean_energy", "scenic_drive"],
            "key_objects": ["electric vehicle", "scenic highway", "guardrail", "ocean"],
            "brand_suitability_summary": "Brand-safe automotive scene ideal for luxury and EV automotive brands.",
        },
        4: {
            "dominant_activity": "Family relaxing by the pool at a tropical luxury resort overlooking the beach",
            "setting": "Tropical resort pool deck",
            "sentiment": SentimentEnum.UPLIFTING.value,
            "garm_safety_tags": [GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            "contextual_tags": ["travel", "vacation", "resort", "hotel", "beach", "relaxation"],
            "key_objects": ["lounge chairs", "swimming pool", "sun umbrellas", "palm trees"],
            "brand_suitability_summary": "Brand-safe travel scene ideal for hospitality and luxury vacation brands.",
        },
        5: {
            "dominant_activity": "Morning skincare wellness routine in bright spa bathroom",
            "setting": "Sunlit minimalist bathroom",
            "sentiment": SentimentEnum.POSITIVE.value,
            "garm_safety_tags": [GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            "contextual_tags": ["skincare", "beauty", "self_care", "morning_routine", "wellness"],
            "key_objects": ["face serum", "mirror", "towel", "natural plants"],
            "brand_suitability_summary": "Brand-safe wellness scene ideal for skincare and cosmetics brands.",
        },
        6: {
            "dominant_activity": "Financial advisor presenting retirement investment growth charts to clients",
            "setting": "Executive conference room",
            "sentiment": SentimentEnum.POSITIVE.value,
            "garm_safety_tags": [GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            "contextual_tags": ["finance", "investing", "retirement", "wealth", "stability"],
            "key_objects": ["financial charts", "tablet", "briefcase", "glass table"],
            "brand_suitability_summary": "Brand-safe financial scene ideal for wealth management and banking.",
        },
        7: {
            "dominant_activity": "Violent vehicle collision on wet mountain road with visible wreckage",
            "setting": "Mountain road at night during heavy rain",
            "sentiment": SentimentEnum.TENSE.value,
            "garm_safety_tags": [GARMSafetyTag.DEATH_INJURY.value],
            "contextual_tags": ["automotive", "car_accident", "driving", "traffic_collision"],
            "key_objects": ["wrecked car", "guardrail", "shattered glass", "emergency lights"],
            "brand_suitability_summary": "Unsafe scene containing vehicle collision and injury risk.",
        },
        8: {
            "dominant_activity": "Armed robbery and physical altercation inside storefront",
            "setting": "Urban retail store",
            "sentiment": SentimentEnum.NEGATIVE.value,
            "garm_safety_tags": [
                GARMSafetyTag.CRIME_ILLEGAL.value,
                GARMSafetyTag.ARMS_WEAPONS.value,
                GARMSafetyTag.DEATH_INJURY.value,
            ],
            "contextual_tags": ["crime", "robbery", "violence", "weapons"],
            "key_objects": ["weapon", "broken glass", "cash register"],
            "brand_suitability_summary": "Severe GARM brand safety violations: crime, weapons, and injury.",
        },
    }

    def __init__(self, registered_scenes: Optional[Dict[int, Dict[str, Any]]] = None) -> None:
        self.custom_scenes: Dict[int, Dict[str, Any]] = registered_scenes.copy() if registered_scenes else {}

    def register_scene(self, scene_id: int, scene_data: Dict[str, Any]) -> None:
        """Registers or overrides deterministic data for a specific scene_id."""
        self.custom_scenes[scene_id] = scene_data

    def analyze_scene(
        self,
        scene_id: int,
        keyframe_data: Optional[Union[str, bytes, List[str]]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        dominant_activity_hint: Optional[str] = None,
        safety_tags_hint: Optional[List[str]] = None,
        context_tags_hint: Optional[List[str]] = None,
        sentiment_hint: Optional[str] = None,
    ) -> SceneUnderstanding:
        """Deterministically analyzes a scene based on scene_id, hints, or registered profiles."""
        # 1. Check custom overrides
        if scene_id in self.custom_scenes:
            profile = dict(self.custom_scenes[scene_id])
        elif scene_id in self.DETERMINISTIC_SCENES:
            profile = dict(self.DETERMINISTIC_SCENES[scene_id])
        else:
            # Deterministic modulo fallback
            default_idx = scene_id % len(self.DETERMINISTIC_SCENES)
            profile = dict(self.DETERMINISTIC_SCENES[default_idx])
            profile["dominant_activity"] = f"Activity in scene {scene_id}: {profile['dominant_activity']}"

        # 2. Apply any explicit hints provided by caller
        if dominant_activity_hint:
            profile["dominant_activity"] = dominant_activity_hint
        if safety_tags_hint is not None:
            profile["garm_safety_tags"] = safety_tags_hint
        if context_tags_hint is not None:
            profile["contextual_tags"] = context_tags_hint
        if sentiment_hint:
            profile["sentiment"] = sentiment_hint

        # 3. Construct and return SceneUnderstanding model
        return SceneUnderstanding(
            scene_id=scene_id,
            start_time=start_time,
            end_time=end_time,
            dominant_activity=profile["dominant_activity"],
            setting=profile.get("setting", "Standard indoor setting"),
            sentiment=profile.get("sentiment", "neutral"),
            garm_safety_tags=profile.get("garm_safety_tags", [GARMSafetyTag.SAFE_ALL_AUDIENCES.value]),
            contextual_tags=profile.get("contextual_tags", ["general"]),
            key_objects=profile.get("key_objects", []),
            brand_suitability_summary=profile.get("brand_suitability_summary", "Deterministic mock evaluation."),
            confidence=1.0,
        )


class GeminiSceneAnalyzer:
    """Multimodal video scene analyzer using Google Gemini API with mock fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-3.8-flash",
        timeout: float = 20.0,
        fallback_mock: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        self.model_name = model_name
        self.timeout = timeout
        self.fallback_mock = fallback_mock
        self.mock_analyzer = MockGeminiAnalyzer()

    @property
    def is_online(self) -> bool:
        """Returns True if a non-empty API key is present."""
        return bool(self.api_key)

    def analyze_scene(
        self,
        scene_id: int,
        keyframe_data: Optional[Union[str, bytes, List[str], Path]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        **hints: Any,
    ) -> SceneUnderstanding:
        """Analyzes a scene using Gemini API if configured, falling back to mock analyzer."""
        if not self.is_online:
            logger.info("GEMINI_API_KEY is not configured. Using deterministic MockGeminiAnalyzer.")
            return self.mock_analyzer.analyze_scene(
                scene_id=scene_id,
                keyframe_data=keyframe_data,
                start_time=start_time,
                end_time=end_time,
                **hints,
            )

        try:
            return self._call_gemini_api(
                scene_id=scene_id,
                keyframe_data=keyframe_data,
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as exc:
            logger.warning(
                "Gemini API request failed for scene %d: %s. %s",
                scene_id,
                exc,
                "Falling back to mock analyzer." if self.fallback_mock else "Reraising exception.",
            )
            if self.fallback_mock:
                return self.mock_analyzer.analyze_scene(
                    scene_id=scene_id,
                    keyframe_data=keyframe_data,
                    start_time=start_time,
                    end_time=end_time,
                    **hints,
                )
            raise

    def _call_gemini_api(
        self,
        scene_id: int,
        keyframe_data: Optional[Union[str, bytes, List[str], Path]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> SceneUnderstanding:
        """Executes actual HTTPS REST API call to Google Gemini endpoint."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

        parts: List[Dict[str, Any]] = [
            {"text": GEMINI_PROMPT_TEMPLATE}
        ]

        import time
        # Process image input if provided
        inline_image = self._encode_image_part(keyframe_data)
        if inline_image:
            parts.append(inline_image)

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        }

        max_retries = 3
        for attempt in range(max_retries):
            resp = requests.post(url, json=payload, timeout=self.timeout)
            if resp.status_code == 429:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    raise RuntimeError(f"Gemini API returned HTTP {resp.status_code} after retries: {resp.text}")
            elif resp.status_code != 200:
                raise RuntimeError(f"Gemini API returned HTTP {resp.status_code}: {resp.text}")
            break

        data = resp.json()
        raw_text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        raw_text = raw_text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        try:
            parsed_json = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse Gemini response as JSON: {raw_text}") from e

        # Normalize safety tags
        raw_safety_tags = parsed_json.get("garm_safety_tags", [])
        validated_safety_tags = [
            tag for tag in raw_safety_tags if tag in ALL_GARM_TAGS
        ]
        if not validated_safety_tags:
            validated_safety_tags = [GARMSafetyTag.SAFE_ALL_AUDIENCES.value]

        return SceneUnderstanding(
            scene_id=scene_id,
            start_time=start_time,
            end_time=end_time,
            dominant_activity=parsed_json.get("dominant_activity", "Unknown activity"),
            setting=parsed_json.get("setting", "General location"),
            sentiment=parsed_json.get("sentiment", "neutral").lower(),
            garm_safety_tags=validated_safety_tags,
            contextual_tags=parsed_json.get("contextual_tags", []),
            key_objects=parsed_json.get("key_objects", []),
            brand_suitability_summary=parsed_json.get("brand_suitability_summary"),
            confidence=1.0,
        )

    def _encode_image_part(
        self, keyframe_data: Optional[Union[str, bytes, List[str], Path]]
    ) -> Optional[Dict[str, Any]]:
        """Encodes image bytes to Gemini inline_data format."""
        if keyframe_data is None:
            return None

        # If list of paths, use the first keyframe
        if isinstance(keyframe_data, list) and keyframe_data:
            keyframe_data = keyframe_data[0]

        img_bytes: Optional[bytes] = None
        if isinstance(keyframe_data, (str, Path)):
            p = Path(keyframe_data)
            if p.exists() and p.is_file():
                img_bytes = p.read_bytes()
        elif isinstance(keyframe_data, bytes):
            img_bytes = keyframe_data

        if img_bytes:
            b64_str = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": b64_str,
                }
            }
        return None
