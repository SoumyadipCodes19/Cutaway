from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class SentimentEnum(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UPLIFTING = "uplifting"
    EXCITING = "exciting"
    TENSE = "tense"
    SAD = "sad"


class GARMSafetyTag(str, Enum):
    ADULT_CONTENT = "adult_content"
    ARMS_WEAPONS = "arms_weapons"
    CRIME_ILLEGAL = "crime_illegal"
    DEATH_INJURY = "death_injury"
    HATE_SPEECH = "hate_speech"
    MILITARY_CONFLICT = "military_conflict"
    OBSCENITY_PROFANITY = "obscenity_profanity"
    SUBSTANCE_ABUSE = "substance_abuse"
    TOBACCO_NICOTINE = "tobacco_nicotine"
    TERRORISM = "terrorism"
    SENSITIVE_SOCIAL_ISSUES = "sensitive_social_issues"
    SAFE_ALL_AUDIENCES = "safe_all_audiences"


ALL_GARM_TAGS: List[str] = [tag.value for tag in GARMSafetyTag]


class SceneUnderstanding(BaseModel):
    """Semantic, sentiment, and brand safety analysis of a video scene."""
    scene_id: int
    dominant_activity: str
    setting: str
    sentiment: str  # "positive", "neutral", "negative", "uplifting", "tense", etc.
    garm_safety_tags: List[str] = Field(default_factory=list)  # subset of 12 GARM categories
    contextual_tags: List[str] = Field(default_factory=list)
    key_objects: List[str] = Field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    brand_suitability_summary: Optional[str] = None
    confidence: float = 1.0

    @model_validator(mode="before")
    @classmethod
    def sync_context_tags(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Synchronize context_tags and contextual_tags aliases
            if "context_tags" in data and "contextual_tags" not in data:
                data["contextual_tags"] = data["context_tags"]
            elif "contextual_tags" in data and "context_tags" not in data:
                data["context_tags"] = data["contextual_tags"]
            # Synchronize safety_tags and garm_safety_tags aliases
            if "safety_tags" in data and "garm_safety_tags" not in data:
                data["garm_safety_tags"] = data["safety_tags"]
            elif "garm_safety_tags" in data and "safety_tags" not in data:
                data["safety_tags"] = data["garm_safety_tags"]
        return data

    @property
    def context_tags(self) -> List[str]:
        return self.contextual_tags

    @property
    def safety_tags(self) -> List[str]:
        return self.garm_safety_tags


class Brand(BaseModel):
    """Synthetic brand definition with affinity rules and safety gating."""
    id: str
    name: str
    category: str
    positive_contexts: List[str] = Field(default_factory=list)
    negative_contexts: List[str] = Field(default_factory=list)
    creative_url: str = Field(default="")
    ad_creative_file: Optional[str] = None
    duration_seconds: Optional[int] = 15
    click_through_url: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sync_creative_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            ad_file = data.get("ad_creative_file")
            creative_url = data.get("creative_url")
            if not creative_url and ad_file:
                data["creative_url"] = ad_file
            elif not ad_file and creative_url:
                data["ad_creative_file"] = creative_url
        return data


class BrandEvaluation(BaseModel):
    """Detailed score evaluation of a brand for a specific scene or break."""
    brand_id: str
    brand_name: Optional[str] = None
    score: float
    is_gated: bool
    rejection_reason: Optional[str] = None
    matched_positive_contexts: List[str] = Field(default_factory=list)
    intersected_negative_contexts: List[str] = Field(default_factory=list)
    context_score: float = 0.0
    sentiment_score: float = 0.0
    safety_score: float = 0.0


class BrandMatchResult(BaseModel):
    """Outcome of evaluating all brands for a candidate break."""
    break_id: str
    selected_brand_id: Optional[str] = None
    selected_brand: Optional[Brand] = None
    winning_score: float = 0.0
    is_dropped: bool = False
    break_action: str = "KEEP_BREAK"  # "KEEP_BREAK" or "DROP_BREAK"
    reason: Optional[str] = None
    evaluations: List[BrandEvaluation] = Field(default_factory=list)
