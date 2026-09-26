"""Comprehensive Unit Test Suite for Milestone 2: Scene Understanding & Brand Matching Engine.

Verifies:
1. Pydantic models (SceneUnderstanding, Brand, BrandEvaluation, BrandMatchResult).
2. 8 Predefined synthetic brands in backend/data/brands.json.
3. Hard Gating: If scene tags/tokens intersect brand's negative_contexts, score is -inf, is_gated=True.
   Guarantees 100% zero overlap.
4. Positive affinity scoring: Context overlap (+20 tag, +10 token, cap 60), sentiment (+20/+5/-10/-20),
   and safety headroom (+20).
5. Top brand selection & break drop rule when all brands are gated or score <= 0.
6. Dynamic loading of unseen 9th brand via JSON file and runtime API with zero code modifications.
7. GeminiSceneAnalyzer and deterministic MockGeminiAnalyzer offline fallback.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.engine.brand_matcher import (
    DEFAULT_CATALOGUE_PATH,
    BrandMatcher,
    normalize_text_tokens,
)
from backend.engine.gemini_analyzer import (
    GeminiSceneAnalyzer,
    MockGeminiAnalyzer,
)
from backend.models.brand_models import (
    ALL_GARM_TAGS,
    Brand,
    BrandEvaluation,
    BrandMatchResult,
    GARMSafetyTag,
    SceneUnderstanding,
    SentimentEnum,
)


# ============================================================================
# 1. Pydantic Model & Catalogue Data Validation Tests
# ============================================================================

def test_scene_understanding_model_validation():
    """Validates SceneUnderstanding instantiation, properties, and tag syncing."""
    scene = SceneUnderstanding(
        scene_id=42,
        dominant_activity="Person running on treadmill",
        setting="Fitness gym",
        sentiment=SentimentEnum.POSITIVE.value,
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["fitness", "running", "gym"],
        key_objects=["treadmill", "dumbbells"],
        start_time=10.0,
        end_time=15.0,
    )
    assert scene.scene_id == 42
    assert scene.dominant_activity == "Person running on treadmill"
    assert scene.sentiment == "positive"
    assert scene.garm_safety_tags == ["safe_all_audiences"]
    assert scene.safety_tags == ["safe_all_audiences"]
    assert scene.contextual_tags == ["fitness", "running", "gym"]
    assert scene.context_tags == ["fitness", "running", "gym"]
    assert len(scene.key_objects) == 2


def test_scene_understanding_dict_alias_sync():
    """Validates backward-compatible alias sync when dict keys use context_tags/safety_tags."""
    data = {
        "scene_id": 1,
        "dominant_activity": "Cooking dinner",
        "setting": "Kitchen",
        "sentiment": "neutral",
        "safety_tags": ["safe_all_audiences"],
        "context_tags": ["cooking", "food"],
    }
    scene = SceneUnderstanding(**data)
    assert scene.garm_safety_tags == ["safe_all_audiences"]
    assert scene.contextual_tags == ["cooking", "food"]


def test_standard_8_brands_catalogue_file_exists():
    """Verifies that backend/data/brands.json contains exactly 8 valid distinct brands."""
    assert DEFAULT_CATALOGUE_PATH.exists(), f"Missing catalogue at {DEFAULT_CATALOGUE_PATH}"
    with open(DEFAULT_CATALOGUE_PATH, "r", encoding="utf-8") as f:
        brands_data = json.load(f)

    assert len(brands_data) == 8, f"Expected 8 brands, found {len(brands_data)}"
    brand_ids = set()

    for item in brands_data:
        brand = Brand(**item)
        assert brand.id, "Brand ID must be non-empty"
        assert brand.name, "Brand Name must be non-empty"
        assert brand.category, "Brand Category must be non-empty"
        assert len(brand.positive_contexts) > 0, f"Brand {brand.id} must have positive contexts"
        assert len(brand.negative_contexts) > 0, f"Brand {brand.id} must have negative contexts"
        assert brand.creative_url, f"Brand {brand.id} must have creative_url"
        brand_ids.add(brand.id)

    # All 8 IDs must be distinct
    assert len(brand_ids) == 8


# ============================================================================
# 2. Hard Gating & 100% Zero Overlap Tests
# ============================================================================

def test_hard_gating_negative_context_scores_negative_inf():
    """Verifies that intersecting a brand's negative_contexts triggers -inf score and is_gated=True."""
    matcher = BrandMatcher()
    apex = matcher.get_brand("apex_athletics")
    assert apex is not None

    # apex_athletics has negative_contexts: ["substance_abuse", "tobacco_nicotine", "death_injury", ...]
    lead_scene = SceneUnderstanding(
        scene_id=1,
        dominant_activity="Person smoking cigarette in dark alley",
        setting="Alleyway",
        sentiment="negative",
        garm_safety_tags=[GARMSafetyTag.TOBACCO_NICOTINE.value],
        contextual_tags=["urban", "night"],
    )

    ev = matcher.evaluate_brand_match(lead_scene, None, apex)
    assert ev.is_gated is True
    assert ev.score == -math.inf
    assert "tobacco_nicotine" in ev.intersected_negative_contexts
    assert "Hard gate" in (ev.rejection_reason or "")


def test_hard_gating_triggers_on_lead_out_trail_scene():
    """Verifies that a brand is gated out if the lead-out (trail) scene violates negative context."""
    matcher = BrandMatcher()
    zenith = matcher.get_brand("zenith_motors")
    assert zenith is not None

    # Lead scene is completely clean and automotive-friendly
    lead_scene = SceneUnderstanding(
        scene_id=1,
        dominant_activity="Driving scenic mountain highway",
        setting="Mountain pass",
        sentiment="positive",
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["automotive", "driving", "scenic_drive"],
    )

    # Lead-out scene contains car accident
    trail_scene = SceneUnderstanding(
        scene_id=2,
        dominant_activity="Car crash with severe vehicle damage",
        setting="Mountain pass road",
        sentiment="tense",
        garm_safety_tags=[GARMSafetyTag.DEATH_INJURY.value],
        contextual_tags=["car_accident", "wreckage"],
    )

    ev = matcher.evaluate_brand_match(lead_scene, trail_scene, zenith)
    assert ev.is_gated is True
    assert ev.score == -math.inf
    assert any(c in ev.intersected_negative_contexts for c in ["car_accident", "death_injury"])


def test_hard_gating_on_text_tokens_in_activity():
    """Verifies that token extraction in dominant_activity triggers hard gating."""
    matcher = BrandMatcher()
    haven = matcher.get_brand("haven_financial")
    assert haven is not None
    # haven_financial has "bankruptcy" in negative_contexts

    lead_scene = SceneUnderstanding(
        scene_id=3,
        dominant_activity="Company filing for bankruptcy liquidation in federal court",
        setting="Courtroom",
        sentiment="negative",
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["legal", "business"],
    )

    ev = matcher.evaluate_brand_match(lead_scene, None, haven)
    assert ev.is_gated is True
    assert ev.score == -math.inf
    assert "bankruptcy" in ev.intersected_negative_contexts


def test_zero_negative_context_violations_guarantee():
    """Guarantees 100% of chosen brand placements have strictly zero overlap with negative_contexts."""
    matcher = BrandMatcher()

    # Test against various scene combinations
    test_scenes = [
        SceneUnderstanding(
            scene_id=10,
            dominant_activity="Athletes training for marathon",
            setting="Stadium track",
            sentiment="uplifting",
            garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            contextual_tags=["fitness", "sports", "running", "training"],
        ),
        SceneUnderstanding(
            scene_id=11,
            dominant_activity="Gourmet baking session",
            setting="Home kitchen",
            sentiment="positive",
            garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            contextual_tags=["cooking", "baking", "food", "kitchen"],
        ),
        SceneUnderstanding(
            scene_id=12,
            dominant_activity="Executive reading quarterly report",
            setting="Modern office",
            sentiment="positive",
            garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
            contextual_tags=["technology", "business", "corporate"],
        ),
    ]

    for sc in test_scenes:
        res = matcher.evaluate_break(break_id=f"break-{sc.scene_id}", lead_in_scene=sc)
        if not res.is_dropped and res.selected_brand:
            winning_brand = res.selected_brand
            # Check overlap manually
            lead_tags, lead_tokens = matcher._extract_scene_signals(sc)
            all_signals = lead_tags | lead_tokens
            overlap = all_signals & set(c.lower() for c in winning_brand.negative_contexts)
            assert len(overlap) == 0, f"Violation detected: {overlap} for brand {winning_brand.id}"


# ============================================================================
# 3. Context Affinity Scoring Logic Tests
# ============================================================================

def test_context_affinity_scoring_calculation():
    """Verifies context tag (+20), token match (+10), sentiment, and safety weights."""
    matcher = BrandMatcher()
    culinary = matcher.get_brand("culinary_craft")
    assert culinary is not None

    # Positive contexts include: "cooking", "chef", "gourmet", "kitchen", "recipe", "dining", "food", ...
    # Scene has 2 tag matches ("cooking", "food") -> 2 * 20 = 40
    # Scene has 1 token match in key_objects ("chef") -> +10
    # Total context score = 50.0 (capped at 60)
    # Sentiment is "positive" -> +20.0
    # Safety is "safe_all_audiences" -> +20.0
    # Expected total score = 50 + 20 + 20 = 90.0
    scene = SceneUnderstanding(
        scene_id=20,
        dominant_activity="Preparing meal for family dinner",
        setting="Cozy room",
        sentiment="positive",
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["cooking", "food"],
        key_objects=["chef apron", "pot"],
    )

    ev = matcher.evaluate_brand_match(scene, None, culinary)
    assert ev.is_gated is False
    assert ev.context_score == 50.0
    assert ev.sentiment_score == 20.0
    assert ev.safety_score == 20.0
    assert ev.score == 90.0


def test_context_affinity_cap_at_60():
    """Verifies that context score is strictly capped at 60.0 even with many matches."""
    matcher = BrandMatcher()
    apex = matcher.get_brand("apex_athletics")
    assert apex is not None

    # 4 tag matches -> 4 * 20 = 80 -> should clamp to 60.0
    scene = SceneUnderstanding(
        scene_id=21,
        dominant_activity="Workout session with running and athletics",
        setting="Gym",
        sentiment="positive",
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["fitness", "sports", "running", "workout"],
    )

    ev = matcher.evaluate_brand_match(scene, None, apex)
    assert ev.context_score == 60.0


def test_sentiment_penalty_and_safety_deduction():
    """Verifies sentiment penalties and lack of safety headroom for non-safe scenes."""
    matcher = BrandMatcher()
    apex = matcher.get_brand("apex_athletics")
    assert apex is not None

    # Negative sentiment (-20), not gated, but has sensitive_social_issues (so safety_score = 0)
    # Note: apex negative_contexts do not include "sensitive_social_issues"
    scene = SceneUnderstanding(
        scene_id=22,
        dominant_activity="Tense debate about athletics policy",
        setting="Conference hall",
        sentiment="negative",
        garm_safety_tags=[GARMSafetyTag.SENSITIVE_SOCIAL_ISSUES.value],
        contextual_tags=["athletics"],
    )

    ev = matcher.evaluate_brand_match(scene, None, apex)
    assert ev.is_gated is False
    assert ev.context_score == 20.0  # 1 tag match: athletics (+20)
    assert ev.sentiment_score == -20.0  # negative sentiment (-20)
    assert ev.safety_score == 0.0  # not safe_all_audiences
    assert ev.score == 0.0  # max(0.0, 20 - 20 + 0) = 0.0


# ============================================================================
# 4. Break Dropping & Selection Rules Tests
# ============================================================================

def test_break_drop_when_all_brands_gated():
    """Verifies break is dropped if all brands are hard-gated out."""
    matcher = BrandMatcher()

    # Scene containing death_injury, crime_illegal, substance_abuse, military_conflict
    # This intersects negative_contexts for all 8 predefined brands
    catastrophic_scene = SceneUnderstanding(
        scene_id=99,
        dominant_activity="Violent military conflict with casualties, illegal crime and substance abuse",
        setting="War zone",
        sentiment="negative",
        garm_safety_tags=[
            GARMSafetyTag.DEATH_INJURY.value,
            GARMSafetyTag.MILITARY_CONFLICT.value,
            GARMSafetyTag.CRIME_ILLEGAL.value,
            GARMSafetyTag.SUBSTANCE_ABUSE.value,
        ],
        contextual_tags=["war", "disaster"],
    )

    result = matcher.evaluate_break(break_id="break-test-drop", lead_in_scene=catastrophic_scene)
    assert result.is_dropped is True
    assert result.break_action == "DROP_BREAK"
    assert result.selected_brand_id is None
    assert result.selected_brand is None
    assert result.winning_score == 0.0
    assert all(ev.is_gated for ev in result.evaluations)


def test_break_drop_when_all_scores_zero():
    """Verifies break is dropped if brands are not gated but all scores are <= 0."""
    # Custom catalogue with a brand that has zero overlap and negative sentiment
    niche_brand = Brand(
        id="deep_sea_drilling",
        name="Deep Sea Drilling Co",
        category="Industrial",
        positive_contexts=["submarine", "offshore_drilling"],
        negative_contexts=["death_injury"],
        creative_url="ads/drilling.mp4",
    )
    matcher = BrandMatcher(catalogue=[niche_brand])

    scene = SceneUnderstanding(
        scene_id=30,
        dominant_activity="Person sitting quietly in empty room looking sad",
        setting="Living room",
        sentiment="sad",  # sentiment score = -10
        garm_safety_tags=[GARMSafetyTag.SENSITIVE_SOCIAL_ISSUES.value],  # safety score = 0, so total <= 0
        contextual_tags=["general"],
    )

    result = matcher.evaluate_break(break_id="break-zero-score", lead_in_scene=scene)
    assert result.is_dropped is True
    assert result.break_action == "DROP_BREAK"
    assert result.selected_brand_id is None


def test_top_brand_selection_and_tie_breaking():
    """Verifies winning brand is selected by top score, breaking ties alphabetically by id."""
    brand_a = Brand(
        id="alpha_brand",
        name="Alpha Brand",
        category="General",
        positive_contexts=["travel"],
        negative_contexts=["death_injury"],
        creative_url="ads/alpha.mp4",
    )
    brand_b = Brand(
        id="beta_brand",
        name="Beta Brand",
        category="General",
        positive_contexts=["travel"],
        negative_contexts=["death_injury"],
        creative_url="ads/beta.mp4",
    )
    # Both brands get identical scores for a travel scene
    matcher = BrandMatcher(catalogue=[brand_b, brand_a])  # inserted in reverse order

    scene = SceneUnderstanding(
        scene_id=31,
        dominant_activity="Walking along vacation resort",
        setting="Resort",
        sentiment="positive",
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["travel"],
    )

    result = matcher.evaluate_break(break_id="break-tie", lead_in_scene=scene)
    assert result.is_dropped is False
    assert result.break_action == "KEEP_BREAK"
    # Tie-break alphabetically: "alpha_brand" < "beta_brand"
    assert result.selected_brand_id == "alpha_brand"


# ============================================================================
# 5. Dynamic 9th Brand Injection Tests (Zero Code Changes)
# ============================================================================

def test_unseen_9th_brand_via_json_file(tmp_path: Path):
    """Verifies adding an unseen 9th brand to an external JSON file works with zero code changes."""
    # 1. Load original 8 brands
    with open(DEFAULT_CATALOGUE_PATH, "r", encoding="utf-8") as f:
        catalogue = json.load(f)
    assert len(catalogue) == 8

    # 2. Append unseen 9th brand ("cyber_shield_security")
    unseen_brand = {
        "id": "cyber_shield_security",
        "name": "CyberShield Defense",
        "category": "Cybersecurity & IT Infrastructure",
        "positive_contexts": [
            "cybersecurity", "tech", "computers", "coding",
            "data_center", "encryption", "privacy"
        ],
        "negative_contexts": [
            "terrorism", "hate_speech", "adult_content",
            "death_injury", "military_conflict"
        ],
        "ad_creative_file": "ads/cyber_shield.mp4",
        "duration_seconds": 15,
        "click_through_url": "https://cybershield.example.com",
    }
    catalogue.append(unseen_brand)

    custom_json = tmp_path / "brands_9.json"
    with open(custom_json, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, indent=2)

    # 3. Instantiate matcher pointing to custom JSON catalogue
    matcher = BrandMatcher(catalogue_path=custom_json)
    assert len(matcher.brands) == 9

    # 4. Evaluate against a specialized cybersecurity coding scene
    scene = SceneUnderstanding(
        scene_id=40,
        dominant_activity="Security analyst typing in terminal configuring data center encryption",
        setting="Data center server room",
        sentiment="positive",
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["cybersecurity", "encryption", "privacy", "coding"],
    )

    result = matcher.evaluate_break(break_id="break-cyber-break", lead_in_scene=scene)
    assert result.is_dropped is False
    assert result.selected_brand_id == "cyber_shield_security"
    assert result.selected_brand is not None
    assert result.selected_brand.name == "CyberShield Defense"
    assert result.winning_score > 0.0


def test_unseen_9th_brand_via_runtime_add_brand():
    """Verifies adding a 9th brand at runtime via add_brand() API works without code modification."""
    matcher = BrandMatcher()
    assert len(matcher.brands) == 8

    brand_9 = {
        "id": "solar_flare_energy",
        "name": "SolarFlare Renewable Power",
        "category": "Clean Energy & Utilities",
        "positive_contexts": ["solar_energy", "clean_power", "green_tech", "sustainability"],
        "negative_contexts": ["pollution", "oil_spill", "coal", "death_injury"],
        "creative_url": "ads/solar_flare.mp4",
    }
    matcher.add_brand(brand_9)
    assert len(matcher.brands) == 9

    scene = SceneUnderstanding(
        scene_id=41,
        dominant_activity="Installing solar panels on residential roof",
        setting="Rooftop in sunny neighborhood",
        sentiment="uplifting",
        garm_safety_tags=[GARMSafetyTag.SAFE_ALL_AUDIENCES.value],
        contextual_tags=["solar_energy", "sustainability", "clean_power"],
    )

    result = matcher.evaluate_break(break_id="break-solar", lead_in_scene=scene)
    assert result.is_dropped is False
    assert result.selected_brand_id == "solar_flare_energy"


# ============================================================================
# 6. Gemini Scene Analyzer & Deterministic Offline Mock Tests
# ============================================================================

def test_mock_gemini_analyzer_deterministic_output():
    """Verifies MockGeminiAnalyzer produces structured SceneUnderstanding for known scene IDs."""
    mock_analyzer = MockGeminiAnalyzer()

    # Scene 0 is outdoor jogging / fitness
    sc0 = mock_analyzer.analyze_scene(scene_id=0)
    assert sc0.scene_id == 0
    assert "fitness" in sc0.contextual_tags
    assert sc0.garm_safety_tags == ["safe_all_audiences"]
    assert sc0.sentiment == "uplifting"

    # Scene 7 is violent car collision (tense, death_injury)
    sc7 = mock_analyzer.analyze_scene(scene_id=7)
    assert sc7.scene_id == 7
    assert "death_injury" in sc7.garm_safety_tags
    assert "car_accident" in sc7.contextual_tags


def test_mock_gemini_analyzer_custom_registration_and_hints():
    """Verifies MockGeminiAnalyzer honors registered overrides and explicit hints."""
    mock_analyzer = MockGeminiAnalyzer()

    # Test hint overrides
    sc_hint = mock_analyzer.analyze_scene(
        scene_id=105,
        dominant_activity_hint="Extreme skateboarding tournament",
        sentiment_hint="exciting",
        context_tags_hint=["sports", "skateboarding"],
    )
    assert sc_hint.dominant_activity == "Extreme skateboarding tournament"
    assert sc_hint.sentiment == "exciting"
    assert sc_hint.contextual_tags == ["sports", "skateboarding"]

    # Test custom registration
    mock_analyzer.register_scene(
        scene_id=200,
        scene_data={
            "dominant_activity": "Space station astronaut spacewalk",
            "setting": "Low Earth orbit",
            "sentiment": "uplifting",
            "garm_safety_tags": ["safe_all_audiences"],
            "contextual_tags": ["space", "technology", "astronomy"],
            "key_objects": ["spacesuit", "solar array"],
        },
    )
    sc_reg = mock_analyzer.analyze_scene(scene_id=200)
    assert sc_reg.scene_id == 200
    assert "space" in sc_reg.contextual_tags
    assert sc_reg.dominant_activity == "Space station astronaut spacewalk"


def test_gemini_analyzer_offline_fallback_when_api_key_unset():
    """Verifies GeminiSceneAnalyzer falls back to mock analyzer when API key is not configured."""
    with patch.dict("os.environ", {}, clear=True):
        analyzer = GeminiSceneAnalyzer(api_key=None, fallback_mock=True)
        assert analyzer.is_online is False

        scene = analyzer.analyze_scene(scene_id=1)
        assert isinstance(scene, SceneUnderstanding)
        assert scene.scene_id == 1
        assert "cooking" in scene.contextual_tags


def test_gemini_analyzer_network_failure_falls_back():
    """Verifies that an online analyzer encountering a network error falls back to mock."""
    analyzer = GeminiSceneAnalyzer(api_key="fake-test-key-12345", fallback_mock=True)
    assert analyzer.is_online is True

    with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Network down")):
        scene = analyzer.analyze_scene(scene_id=2)
        assert isinstance(scene, SceneUnderstanding)
        assert scene.scene_id == 2
        assert "technology" in scene.contextual_tags


def test_gemini_analyzer_online_response_parsing():
    """Verifies correct parsing of a successful Gemini API JSON response."""
    analyzer = GeminiSceneAnalyzer(api_key="valid-mock-key", fallback_mock=False)

    gemini_json_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "dominant_activity": "Barista making latte art",
                                "setting": "Artisan coffee shop",
                                "sentiment": "positive",
                                "garm_safety_tags": ["safe_all_audiences"],
                                "contextual_tags": ["beverage", "coffee", "lifestyle"],
                                "key_objects": ["espresso machine", "cup"],
                                "brand_suitability_summary": "Brand safe coffee shop scene.",
                            })
                        }
                    ]
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = gemini_json_payload

    with patch("requests.post", return_value=mock_resp):
        scene = analyzer.analyze_scene(scene_id=50)
        assert scene.scene_id == 50
        assert scene.dominant_activity == "Barista making latte art"
        assert scene.sentiment == "positive"
        assert scene.garm_safety_tags == ["safe_all_audiences"]
        assert "coffee" in scene.contextual_tags
