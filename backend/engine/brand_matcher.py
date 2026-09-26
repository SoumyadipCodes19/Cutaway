"""Brand Matching & Brand Safety Gating Engine.

Implements:
- Hard Gating: If scene tags/tokens intersect a brand's negative_contexts,
  score is -inf, is_gated = True (guaranteeing 100% zero overlap).
- Positive Contextual & Sentiment Affinity Scoring: Context overlap, sentiment,
  and safety headroom.
- Top Brand Selection & Break Dropping: Selects the winning brand or drops the break
  if all brands are gated or score <= 0.
- Dynamic Catalogue Loading: Supports unseen brands (e.g. 9th brand) loaded from JSON
  or injected at runtime with zero code modifications.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from backend.models.brand_models import (
    Brand,
    BrandEvaluation,
    BrandMatchResult,
    SceneUnderstanding,
)

logger = logging.getLogger(__name__)

DEFAULT_CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "brands.json"


def normalize_text_tokens(text: str) -> Set[str]:
    """Tokenizes and normalizes text string to lowercase alphanumeric tokens."""
    if not text:
        return set()
    return set(re.findall(r"\b[a-zA-Z0-9_]+\b", text.lower()))


class BrandMatcher:
    """Contextual brand matching engine with strict brand safety gating."""

    def __init__(
        self,
        catalogue: Optional[List[Union[Brand, Dict[str, Any]]]] = None,
        catalogue_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.brands: List[Brand] = []
        if catalogue is not None:
            self.load_catalogue(catalogue)
        else:
            path = catalogue_path or DEFAULT_CATALOGUE_PATH
            self.load_catalogue(path)

    def load_catalogue(
        self, source: Union[str, Path, List[Union[Brand, Dict[str, Any]]]]
    ) -> List[Brand]:
        """Loads brand catalogue dynamically from a file path or list of dicts/models."""
        self.brands = []
        raw_items: List[Any] = []

        if isinstance(source, (str, Path)):
            p = Path(source)
            if not p.exists():
                raise FileNotFoundError(f"Brand catalogue file not found: {p}")
            with open(p, "r", encoding="utf-8") as f:
                raw_items = json.load(f)
        elif isinstance(source, list):
            raw_items = source
        else:
            raise TypeError(f"Unsupported catalogue source type: {type(source)}")

        for item in raw_items:
            if isinstance(item, Brand):
                self.brands.append(item)
            elif isinstance(item, dict):
                self.brands.append(Brand(**item))
            else:
                raise ValueError(f"Invalid brand item: {item}")

        logger.info("Loaded %d brands into BrandMatcher catalogue.", len(self.brands))
        return self.brands

    def add_brand(self, brand: Union[Brand, Dict[str, Any]]) -> Brand:
        """Dynamically registers an additional brand (e.g. unseen 9th brand) with zero code changes."""
        if isinstance(brand, dict):
            brand_obj = Brand(**brand)
        elif isinstance(brand, Brand):
            brand_obj = brand
        else:
            raise TypeError(f"Expected Brand or dict, got {type(brand)}")

        # Replace existing brand if same ID exists, otherwise append
        for i, existing in enumerate(self.brands):
            if existing.id == brand_obj.id:
                self.brands[i] = brand_obj
                return brand_obj

        self.brands.append(brand_obj)
        logger.info("Added dynamic brand: %s (id: %s)", brand_obj.name, brand_obj.id)
        return brand_obj

    def get_brand(self, brand_id: str) -> Optional[Brand]:
        """Retrieves a brand by ID from the active catalogue."""
        for b in self.brands:
            if b.id == brand_id:
                return b
        return None

    def _extract_scene_signals(
        self, scene: Optional[Union[SceneUnderstanding, Dict[str, Any]]]
    ) -> Tuple[Set[str], Set[str]]:
        """Extracts normalized tags and tokens from a scene."""
        if scene is None:
            return set(), set()

        if isinstance(scene, dict):
            sc_dict = scene
        else:
            sc_dict = scene.model_dump()

        tags: Set[str] = set()
        for t in sc_dict.get("garm_safety_tags", []) or []:
            tags.add(str(t).lower())
        for t in sc_dict.get("contextual_tags", []) or []:
            tags.add(str(t).lower())
        for t in sc_dict.get("context_tags", []) or []:
            tags.add(str(t).lower())

        tokens: Set[str] = set()
        tokens.update(normalize_text_tokens(sc_dict.get("dominant_activity", "")))
        tokens.update(normalize_text_tokens(sc_dict.get("setting", "")))
        for obj in sc_dict.get("key_objects", []) or []:
            tokens.update(normalize_text_tokens(str(obj)))

        return tags, tokens

    def evaluate_brand_match(
        self,
        lead_scene: Union[SceneUnderstanding, Dict[str, Any]],
        trail_scene: Optional[Union[SceneUnderstanding, Dict[str, Any]]],
        brand: Brand,
    ) -> BrandEvaluation:
        """Evaluates a single brand against a break's lead-in and lead-out scenes.
        
        1. Hard Gating:
           If any negative context intersects signals from lead or trail scene:
           score = -inf, is_gated = True.
        2. Context Alignment C in [0, 60]:
           +20 per exact tag match with positive_contexts
           +10 per token match in dominant_activity/setting/key_objects.
        3. Sentiment Alignment M in [-20, 20]:
           +20 for positive/uplifting/exciting, +5 for neutral, -10 for tense/sad, -20 for negative.
        4. Safety Headroom S in [0, 20]:
           +20 if safe_all_audiences and no GARM violation tags, 0 otherwise.
        Total Score = max(0.0, C + M + S).
        """
        neg_contexts = set(c.strip().lower() for c in brand.negative_contexts)
        pos_contexts = set(c.strip().lower() for c in brand.positive_contexts)

        lead_tags, lead_tokens = self._extract_scene_signals(lead_scene)
        trail_tags, trail_tokens = self._extract_scene_signals(trail_scene)

        all_scene_signals = lead_tags | lead_tokens | trail_tags | trail_tokens

        # 1. HARD GATE: Zero Overlap Guarantee
        intersection = all_scene_signals & neg_contexts
        if intersection:
            sorted_violations = sorted(list(intersection))
            return BrandEvaluation(
                brand_id=brand.id,
                brand_name=brand.name,
                score=-float("inf"),
                is_gated=True,
                rejection_reason=(
                    f"Hard gate: scene signals {sorted_violations} intersect brand negative contexts."
                ),
                matched_positive_contexts=[],
                intersected_negative_contexts=sorted_violations,
                context_score=0.0,
                sentiment_score=0.0,
                safety_score=0.0,
            )

        # 2. CONTEXT AFFINITY (Evaluated on lead-in scene)
        context_score = 0.0
        matched_pos: List[str] = []
        for pos in pos_contexts:
            if pos in lead_tags:
                context_score += 20.0
                matched_pos.append(pos)
            elif pos in lead_tokens:
                context_score += 10.0
                matched_pos.append(pos)
        context_score = min(60.0, context_score)

        # 3. SENTIMENT ALIGNMENT
        if isinstance(lead_scene, dict):
            raw_sentiment = lead_scene.get("sentiment", "neutral")
        else:
            raw_sentiment = getattr(lead_scene, "sentiment", "neutral")
        sentiment_val = str(raw_sentiment).lower()

        if sentiment_val in ("positive", "uplifting", "exciting"):
            sentiment_score = 20.0
        elif sentiment_val == "neutral":
            sentiment_score = 5.0
        elif sentiment_val in ("tense", "sad"):
            sentiment_score = -10.0
        elif sentiment_val == "negative":
            sentiment_score = -20.0
        else:
            sentiment_score = 0.0

        # 4. SAFETY HEADROOM
        if isinstance(lead_scene, dict):
            garm_tags = lead_scene.get("garm_safety_tags", [])
        else:
            garm_tags = getattr(lead_scene, "garm_safety_tags", [])

        has_garm_violation = any(str(t).lower() != "safe_all_audiences" for t in garm_tags)
        if not has_garm_violation and len(garm_tags) > 0:
            safety_score = 20.0
        else:
            safety_score = 0.0

        total_score = max(0.0, context_score + sentiment_score + safety_score)

        return BrandEvaluation(
            brand_id=brand.id,
            brand_name=brand.name,
            score=round(total_score, 2),
            is_gated=False,
            rejection_reason=None,
            matched_positive_contexts=sorted(matched_pos),
            intersected_negative_contexts=[],
            context_score=round(context_score, 2),
            sentiment_score=round(sentiment_score, 2),
            safety_score=round(safety_score, 2),
        )

    def evaluate_break(
        self,
        break_id: str,
        lead_in_scene: Union[SceneUnderstanding, Dict[str, Any]],
        lead_out_scene: Optional[Union[SceneUnderstanding, Dict[str, Any]]] = None,
    ) -> BrandMatchResult:
        """Evaluates all catalogue brands for a candidate break.
        
        Selects top scoring non-gated brand with score > 0.
        If all brands are gated or score <= 0, DROPS the break.
        """
        evaluations: List[BrandEvaluation] = []
        eligible: List[Tuple[Brand, float]] = []

        for brand in self.brands:
            ev = self.evaluate_brand_match(lead_in_scene, lead_out_scene, brand)
            evaluations.append(ev)
            if not ev.is_gated and ev.score > 0.0:
                eligible.append((brand, ev.score))

        # Break Drop Rule: if no eligible brands with score > 0, drop the break
        if not eligible:
            return BrandMatchResult(
                break_id=break_id,
                selected_brand_id=None,
                selected_brand=None,
                winning_score=0.0,
                is_dropped=True,
                break_action="DROP_BREAK",
                reason="All brands gated out due to safety violations or zero affinity",
                evaluations=evaluations,
            )

        # Sort eligible brands: highest score first, tie-break alphabetical by brand id
        eligible.sort(key=lambda item: (-item[1], item[0].id))
        winning_brand, winning_score = eligible[0]

        return BrandMatchResult(
            break_id=break_id,
            selected_brand_id=winning_brand.id,
            selected_brand=winning_brand,
            winning_score=winning_score,
            is_dropped=False,
            break_action="KEEP_BREAK",
            reason=f"Matched top brand {winning_brand.name} with score {winning_score}",
            evaluations=evaluations,
        )
