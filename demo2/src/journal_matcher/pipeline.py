from __future__ import annotations

import datetime as _datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .catalog import JournalCatalog
from .llm import JSONLanguageModel
from .msc import MSCTaxonomy, normalize_msc_code
from .prompts import (
    article_profile_prompt,
    broad_msc_prompt,
    central_results_prompt,
    journal_field_profile_prompt,
    journal_match_prompt,
)
from .schemas import (
    ArticleProfile,
    ExtractedManuscript,
    JournalCandidate,
    JournalFieldProfile,
    MSCClassification,
    MatchReport,
    Recommendation,
)


class JournalMatcher:
    """Orchestrates extraction outputs, confirmation, classification, and matching."""

    def __init__(self, model: JSONLanguageModel, taxonomy: MSCTaxonomy, catalog: JournalCatalog) -> None:
        self.model = model
        self.taxonomy = taxonomy
        self.catalog = catalog

    def propose_central_results(self, manuscript: ExtractedManuscript) -> Dict[str, Any]:
        value = self.model.complete_json(central_results_prompt(manuscript))
        if not isinstance(value, Mapping):
            raise ValueError("central-result response must be a JSON object")
        valid_ids = {item.result_id for item in manuscript.theorems}
        candidates = []
        for item in value.get("candidates", []):
            if isinstance(item, Mapping) and (not valid_ids or str(item.get("result_id", "")) in valid_ids):
                candidates.append(dict(item))
        return {"candidates": candidates, "uncertainties": list(value.get("uncertainties", []))}

    def classify_broad(self, manuscript: ExtractedManuscript, central_result_ids: Sequence[str], central_result_text: str = "") -> Dict[str, Any]:
        context = self.taxonomy.prompt_context(item.code for item in self.taxonomy.two_digit())
        value = self.model.complete_json(broad_msc_prompt(manuscript, context, central_result_ids, central_result_text))
        if not isinstance(value, Mapping):
            raise ValueError("broad MSC response must be a JSON object")
        return dict(value)

    def build_profile(
        self,
        manuscript: ExtractedManuscript,
        central_result_ids: Sequence[str],
        broad_classification: Mapping[str, Any],
        central_result_text: str = "",
    ) -> ArticleProfile:
        broad_items = list(broad_classification.get("broad_fields", []))
        broad_codes = [str(item.get("code", "")) for item in broad_items if isinstance(item, Mapping) and item.get("code")]
        detailed_codes: List[str] = []
        for broad_code in broad_codes:
            detailed_codes.extend(item.code for item in self.taxonomy.descendants(broad_code))
        # A sparse local taxonomy should still let the model return a code from
        # the imported MSC file rather than failing before author confirmation.
        detailed_context = self.taxonomy.prompt_context(detailed_codes[:700])
        value = self.model.complete_json(
            article_profile_prompt(
                manuscript,
                central_result_ids,
                self.taxonomy.prompt_context(item.code for item in self.taxonomy.two_digit()),
                detailed_context,
                central_result_text,
            )
        )
        if not isinstance(value, Mapping):
            raise ValueError("article profile response must be a JSON object")
        return self._profile_from_json(value, broad_items)

    def candidates(self, profile: ArticleProfile, limit: int = 24) -> List[JournalCandidate]:
        codes = []
        if profile.primary_msc:
            codes.append(profile.primary_msc.code)
        codes.extend(item.code for item in profile.secondary_msc)
        codes.extend(item.code for item in profile.broad_fields)
        return self.catalog.find_candidates(codes, limit=limit)

    def profile_journals(self, profile: ArticleProfile, candidates: Sequence[JournalCandidate]) -> List[JournalFieldProfile]:
        prefix = profile.primary_msc.code if profile.primary_msc else (profile.broad_fields[0].code if profile.broad_fields else "")
        profiles: List[JournalFieldProfile] = []
        for candidate in candidates:
            cached = self.catalog.get_field_profile(candidate.journal_id, prefix) if prefix else None
            if cached:
                profiles.append(cached)
                continue
            if not candidate.representative_articles:
                field_profile = JournalFieldProfile(journal_id=candidate.journal_id, msc_prefix=prefix, confidence="low")
            else:
                value = self.model.complete_json(journal_field_profile_prompt(profile, candidate))
                if not isinstance(value, Mapping):
                    raise ValueError("journal field profile response must be a JSON object")
                field_profile = JournalFieldProfile(
                    journal_id=candidate.journal_id,
                    msc_prefix=prefix,
                    typical_contributions=list(value.get("typical_contributions", [])),
                    technical_depth_range=list(value.get("technical_depth_range", [])),
                    typical_audience=str(value.get("typical_audience", "unknown")),
                    breadth=str(value.get("breadth", "unknown")),
                    conceptual_character=str(value.get("conceptual_character", "unknown")),
                    article_shape=str(value.get("article_shape", "unknown")),
                    representative_article_ids=list(value.get("representative_article_ids", [])),
                    confidence=str(value.get("confidence", "medium")),
                )
            self.catalog.save_field_profile(field_profile, _datetime.datetime.utcnow().isoformat() + "Z")
            profiles.append(field_profile)
        return profiles

    def match(self, profile: ArticleProfile, candidates: Sequence[JournalCandidate], field_profiles: Sequence[JournalFieldProfile], central_result_text: str = "") -> MatchReport:
        value = self.model.complete_json(
            journal_match_prompt(
                profile,
                [candidate.to_dict() for candidate in candidates],
                [item.to_dict() for item in field_profiles],
            )
        )
        known = {candidate.journal_id: candidate.name for candidate in candidates}
        recommendations: List[Recommendation] = []
        seen = set()
        for item in value.get("recommendations", []) if isinstance(value, Mapping) else []:
            if not isinstance(item, Mapping):
                continue
            journal_id = str(item.get("journal_id", ""))
            if journal_id not in known or journal_id in seen:
                continue
            seen.add(journal_id)
            recommendations.append(
                Recommendation(
                    role=str(item.get("role", "")),
                    journal_id=journal_id,
                    journal_name=known[journal_id],
                    fit=str(item.get("fit", "insufficient information")),
                    reasons=[str(reason) for reason in item.get("reasons", [])],
                    level_fit=str(item.get("level_fit", "insufficient information")),
                    representative_article_ids=[str(article_id) for article_id in item.get("representative_article_ids", [])],
                    important_mismatch=str(item.get("important_mismatch", "")),
                    submission_emphasis=str(item.get("submission_emphasis", "")),
                )
            )
        limitations = [str(item) for item in value.get("limitations", [])] if isinstance(value, Mapping) else ["The matching model returned no usable recommendations."]
        if not candidates:
            limitations.append("The catalog contains no journals with recent evidence for the confirmed MSC area.")
        return MatchReport(central_result_text=central_result_text, profile=profile, recommendations=recommendations, catalog_limitations=limitations)

    @staticmethod
    def _classification(value: Any, role: str) -> Optional[MSCClassification]:
        if not isinstance(value, Mapping) or not value.get("code"):
            return None
        return MSCClassification(
            code=normalize_msc_code(str(value.get("code", ""))),
            name=str(value.get("name", "")),
            role=role,
            confidence=str(value.get("confidence", "medium")),
            evidence=[str(item) for item in value.get("evidence", [])],
        )

    def _profile_from_json(self, value: Mapping[str, Any], broad_items: Iterable[Any]) -> ArticleProfile:
        broad_values = value.get("broad_fields", list(broad_items))
        broad: List[MSCClassification] = []
        for item in broad_values:
            parsed = self._classification(item, str(item.get("role", "secondary")) if isinstance(item, Mapping) else "secondary")
            if parsed:
                broad.append(parsed)
        primary = self._classification(value.get("primary_msc"), "primary")
        secondary: List[MSCClassification] = []
        for item in value.get("secondary_msc", []):
            parsed = self._classification(item, "secondary")
            if parsed:
                secondary.append(parsed)
        return ArticleProfile(
            central_results=list(value.get("central_results", [])),
            broad_fields=broad,
            primary_msc=primary,
            secondary_msc=secondary,
            methods=[str(item) for item in value.get("methods", [])],
            contribution_type=str(value.get("contribution_type", "unknown")),
            claimed_improvement=str(value.get("claimed_improvement", "")),
            prerequisites=str(value.get("prerequisites", "unknown")),
            technical_depth=str(value.get("technical_depth", "unknown")),
            conceptual_character=str(value.get("conceptual_character", "unknown")),
            audience=str(value.get("audience", "unknown")),
            audience_breadth=str(value.get("audience_breadth", "unknown")),
            uncertainties=[str(item) for item in value.get("uncertainties", [])],
        )
