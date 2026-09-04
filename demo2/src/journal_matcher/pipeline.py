from __future__ import annotations

import datetime as _datetime
import math
import re
from dataclasses import replace
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


_LEVELS = {"standard": 1, "advanced": 2, "highly specialized": 3}
_BREADTHS = {"narrow": 1, "subfield": 2, "field": 3, "cross-field": 4}
_STOPWORDS = {
    "and", "the", "for", "with", "from", "using", "into", "this", "that", "are", "article",
    "mathematics", "mathematical", "theory", "results", "paper", "new", "some", "on", "of", "in",
}


def _normalize_level(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", " ")
    if text in {"standard", "typical", "moderate"}:
        return "standard"
    if text in {"advanced", "high"}:
        return "advanced"
    if text in {"highly specialized", "specialized", "highly technical", "expert"}:
        return "highly specialized"
    return "unknown"


def _normalize_breadth(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "-")
    return text if text in _BREADTHS else "unknown"


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z][a-z0-9-]{2,}", str(value or "").lower())
        if token not in _STOPWORDS
    }


def _level_range(values: Iterable[Any]) -> List[int]:
    return sorted({_LEVELS[level] for value in values if (level := _normalize_level(value)) != "unknown"})
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
        # Keep all descendants in the complete taxonomy.  The old first-700
        # slice could silently omit an entire subfield depending on its code.
        detailed_context = self.taxonomy.prompt_context(detailed_codes)
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
        profile = self._profile_from_json(value, broad_items)
        if not profile.keywords:
            source = " ".join(
                [manuscript.title, manuscript.abstract, manuscript.introduction]
                + [item.get("title", "") + " " + item.get("text", "") for item in manuscript.section_contents]
            )
            profile.keywords = sorted(_tokens(source))[:80]
        return profile

    def candidates(self, profile: ArticleProfile, limit: int = 24) -> List[JournalCandidate]:
        codes = []
        if profile.primary_msc:
            codes.append(profile.primary_msc.code)
        codes.extend(item.code for item in profile.secondary_msc)
        codes.extend(item.code for item in profile.broad_fields)
        return self.catalog.find_candidates(codes, limit=limit)

    def rank_candidates(
        self,
        profile: ArticleProfile,
        candidates: Sequence[JournalCandidate],
        field_profiles: Sequence[JournalFieldProfile],
    ) -> List[JournalCandidate]:
        """Rank candidates with transparent field/level/evidence signals.

        This is intentionally small and deterministic.  The language model
        later explains the top results, but it is no longer the only component
        deciding whether a venue is at the right technical level.
        """

        profiles = {item.journal_id: item for item in field_profiles}
        article_level = _LEVELS.get(_normalize_level(profile.technical_depth))
        article_breadth = _BREADTHS.get(_normalize_breadth(profile.audience_breadth))
        query = _tokens(" ".join(profile.keywords + profile.methods + [profile.contribution_type, profile.conceptual_character]))
        tier_scores = {"exact-subfield": 1.0, "subfield": 0.78, "broad-field": 0.48}
        confidence_scores = {"high": 1.0, "medium": 0.75, "low": 0.45}
        ranked: List[JournalCandidate] = []
        for candidate in candidates:
            field = profiles.get(candidate.journal_id)
            range_values = _level_range(field.technical_depth_range if field else ())
            candidate_level = _normalize_level(candidate.technical_level)
            if not range_values and candidate_level != "unknown":
                range_values = [_LEVELS[candidate_level]]
            if article_level is None or not range_values:
                depth_score, level_distance = 0.5, None
            else:
                level_distance = min(abs(article_level - value) for value in range_values)
                depth_score = 1.0 if level_distance == 0 else (0.65 if level_distance == 1 else 0.3)

            journal_breadth = _normalize_breadth(field.breadth if field else candidate.audience_breadth)
            breadth_value = _BREADTHS.get(journal_breadth)
            if article_breadth is None or breadth_value is None:
                breadth_score = 0.5
            else:
                breadth_score = 1.0 if article_breadth == breadth_value else (0.7 if abs(article_breadth - breadth_value) == 1 else 0.4)

            corpus = _tokens(candidate.scope_summary)
            for article in candidate.representative_articles:
                corpus.update(_tokens(article.title + " " + article.abstract))
            lexical_score = len(query & corpus) / max(len(query), 1)
            evidence_count = max(candidate.article_count, len(candidate.representative_articles))
            evidence_score = min(1.0, math.log1p(evidence_count) / math.log1p(20))
            confidence = confidence_scores.get(field.confidence if field else "low", 0.45)
            score = (
                0.30 * tier_scores.get(candidate.tier, 0.4)
                + 0.28 * depth_score
                + 0.14 * breadth_score
                + 0.16 * lexical_score
                + 0.07 * evidence_score
                + 0.05 * confidence
            )
            ranked.append(replace(candidate, match_score=round(score, 4), level_distance=level_distance))
        return sorted(ranked, key=lambda item: (-item.match_score, item.name.casefold(), item.journal_id))

    def profile_journals(self, profile: ArticleProfile, candidates: Sequence[JournalCandidate]) -> List[JournalFieldProfile]:
        prefix = profile.primary_msc.code if profile.primary_msc else (profile.broad_fields[0].code if profile.broad_fields else "")
        profiles: List[JournalFieldProfile] = []
        for candidate in candidates:
            cached = self.catalog.get_field_profile(candidate.journal_id, prefix) if prefix else None
            if cached:
                profiles.append(cached)
                continue
            if not candidate.representative_articles:
                field_profile = JournalFieldProfile(
                    journal_id=candidate.journal_id,
                    msc_prefix=prefix,
                    technical_depth_range=[candidate.technical_level] if _normalize_level(candidate.technical_level) != "unknown" else [],
                    breadth=_normalize_breadth(candidate.audience_breadth),
                    confidence="low",
                )
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
                if not field_profile.technical_depth_range and _normalize_level(candidate.technical_level) != "unknown":
                    field_profile.technical_depth_range = [candidate.technical_level]
                if field_profile.breadth == "unknown":
                    field_profile.breadth = _normalize_breadth(candidate.audience_breadth)
            self.catalog.save_field_profile(field_profile, _datetime.datetime.utcnow().isoformat() + "Z")
            profiles.append(field_profile)
        return profiles

    def match(self, profile: ArticleProfile, candidates: Sequence[JournalCandidate], field_profiles: Sequence[JournalFieldProfile], central_result_text: str = "") -> MatchReport:
        ranked_candidates = self.rank_candidates(profile, candidates, field_profiles)
        # A dozen evidence-backed candidates keeps the prompt small while
        # leaving enough alternatives for broad or interdisciplinary papers.
        ranked_candidates = ranked_candidates[:12]
        value = self.model.complete_json(
            journal_match_prompt(
                profile,
                [candidate.to_dict() for candidate in ranked_candidates],
                [item.to_dict() for item in field_profiles],
            )
        )
        known = {candidate.journal_id: candidate for candidate in ranked_candidates}
        rank_index = {candidate.journal_id: index for index, candidate in enumerate(ranked_candidates)}
        recommendations: List[Recommendation] = []
        seen = set()
        for item in value.get("recommendations", []) if isinstance(value, Mapping) else []:
            if not isinstance(item, Mapping):
                continue
            journal_id = str(item.get("journal_id", ""))
            if journal_id not in known or journal_id in seen:
                continue
            seen.add(journal_id)
            candidate = known[journal_id]
            recommendations.append(
                Recommendation(
                    role=str(item.get("role", "")),
                    journal_id=journal_id,
                    journal_name=candidate.name,
                    fit=str(item.get("fit", "insufficient information")),
                    reasons=[str(reason) for reason in item.get("reasons", [])],
                    level_fit=str(item.get("level_fit", "insufficient information")),
                    representative_article_ids=[str(article_id) for article_id in item.get("representative_article_ids", [])],
                    important_mismatch=str(item.get("important_mismatch", "")),
                    submission_emphasis=str(item.get("submission_emphasis", "")),
                    match_score=candidate.match_score,
                )
            )
        recommendations.sort(key=lambda item: rank_index.get(item.journal_id, len(rank_index)))
        for index, item in enumerate(recommendations):
            if index == 0:
                item.role = "closest field-and-level match"
                continue
            candidate = known[item.journal_id]
            breadth = _BREADTHS.get(_normalize_breadth(candidate.audience_breadth), 0)
            article_breadth = _BREADTHS.get(_normalize_breadth(profile.audience_breadth), 0)
            item.role = "broader-audience alternative" if candidate.tier == "broad-field" or breadth > article_breadth else "more specialized alternative"
        limitations = [str(item) for item in value.get("limitations", [])] if isinstance(value, Mapping) else ["The matching model returned no usable recommendations."]
        if not ranked_candidates:
            limitations.append("The catalog contains no journals with recent evidence for the confirmed MSC area.")
        else:
            usable_articles = sum(
                1
                for candidate in ranked_candidates
                for article in candidate.representative_articles
                if article.title and (article.abstract or article.msc_codes)
            )
            if usable_articles < min(3, len(ranked_candidates)):
                limitations.append("Journal level ranking is based on sparse article evidence for this field.")
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
            technical_depth=_normalize_level(value.get("technical_depth", "unknown")),
            conceptual_character=str(value.get("conceptual_character", "unknown")),
            audience=str(value.get("audience", "unknown")),
            audience_breadth=_normalize_breadth(value.get("audience_breadth", "unknown")),
            keywords=[str(item) for item in value.get("keywords", []) if str(item).strip()],
            uncertainties=[str(item) for item in value.get("uncertainties", [])],
        )
