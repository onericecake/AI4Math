from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TheoremRecord:
    result_id: str
    environment: str
    statement: str
    label: Optional[str] = None
    number: Optional[str] = None
    section: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExtractedManuscript:
    source_path: str
    title: str = ""
    abstract: str = ""
    introduction: str = ""
    sections: List[str] = field(default_factory=list)
    # Section bodies keep the analysis context from being reduced to a list of
    # headings.  ``sections`` remains for backwards compatibility with the
    # original public API.
    section_contents: List[Dict[str, Any]] = field(default_factory=list)
    theorems: List[TheoremRecord] = field(default_factory=list)
    proofs: List[Dict[str, str]] = field(default_factory=list)
    conclusion: str = ""
    bibliography: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["theorems"] = [item.to_dict() for item in self.theorems]
        return value


@dataclass
class MSCClassification:
    code: str
    name: str = ""
    role: str = "primary"
    confidence: str = "medium"
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArticleProfile:
    central_results: List[Dict[str, Any]] = field(default_factory=list)
    broad_fields: List[MSCClassification] = field(default_factory=list)
    primary_msc: Optional[MSCClassification] = None
    secondary_msc: List[MSCClassification] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    contribution_type: str = "unknown"
    claimed_improvement: str = ""
    prerequisites: str = "unknown"
    technical_depth: str = "unknown"
    conceptual_character: str = "unknown"
    audience: str = "unknown"
    audience_breadth: str = "unknown"
    keywords: List[str] = field(default_factory=list)
    uncertainties: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["broad_fields"] = [item.to_dict() for item in self.broad_fields]
        value["primary_msc"] = self.primary_msc.to_dict() if self.primary_msc else None
        value["secondary_msc"] = [item.to_dict() for item in self.secondary_msc]
        return value


@dataclass
class RepresentativeArticle:
    article_id: str
    title: str
    year: Optional[int] = None
    abstract: str = ""
    msc_codes: List[str] = field(default_factory=list)
    doi: Optional[str] = None
    source_url: Optional[str] = None
    article_type: str = "research article"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JournalCandidate:
    journal_id: str
    name: str
    tier: str
    matching_codes: List[str] = field(default_factory=list)
    official_url: Optional[str] = None
    scope_summary: str = ""
    representative_articles: List[RepresentativeArticle] = field(default_factory=list)
    article_count: int = 0
    matching_share: float = 0.0
    technical_level: str = "unknown"
    audience_breadth: str = "unknown"
    match_score: float = 0.0
    level_distance: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["representative_articles"] = [item.to_dict() for item in self.representative_articles]
        return value


@dataclass
class JournalFieldProfile:
    journal_id: str
    msc_prefix: str
    typical_contributions: List[str] = field(default_factory=list)
    technical_depth_range: List[str] = field(default_factory=list)
    typical_audience: str = "unknown"
    breadth: str = "unknown"
    conceptual_character: str = "unknown"
    article_shape: str = "unknown"
    representative_article_ids: List[str] = field(default_factory=list)
    confidence: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Recommendation:
    role: str
    journal_id: str
    journal_name: str
    fit: str
    reasons: List[str] = field(default_factory=list)
    level_fit: str = "insufficient information"
    representative_article_ids: List[str] = field(default_factory=list)
    important_mismatch: str = ""
    submission_emphasis: str = ""
    match_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MatchReport:
    central_result_text: str
    profile: ArticleProfile
    recommendations: List[Recommendation]
    catalog_limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "central_result_text": self.central_result_text,
            "profile": self.profile.to_dict(),
            "recommendations": [item.to_dict() for item in self.recommendations],
            "catalog_limitations": self.catalog_limitations,
        }
