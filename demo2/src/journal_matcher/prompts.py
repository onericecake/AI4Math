from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from .schemas import ArticleProfile, ExtractedManuscript, JournalCandidate


def _manuscript_context(manuscript: ExtractedManuscript) -> str:
    theorem_text = "\n\n".join(
        "[%s | %s]\n%s" % (item.result_id, item.environment, item.statement)
        for item in manuscript.theorems
    )
    bibliography = "\n".join(item.get("text", "") for item in manuscript.bibliography[:80])
    sections = "\n\n".join(
        "[%s | level %s]\n%s" % (item.get("title", ""), item.get("level", ""), item.get("text", ""))
        for item in manuscript.section_contents
    )
    proofs = "\n\n".join(
        "[%s]\n%s" % (item.get("proof_id", ""), item.get("text", ""))
        for item in manuscript.proofs
    )
    return "\n".join(
        [
            "TITLE:\n" + manuscript.title,
            "ABSTRACT:\n" + manuscript.abstract,
            "INTRODUCTION:\n" + manuscript.introduction[:16000],
            "SECTION EVIDENCE:\n" + sections[:36000],
            "RESULTS:\n" + theorem_text[:24000],
            "PROOF EVIDENCE:\n" + proofs[:18000],
            "CONCLUSION:\n" + manuscript.conclusion[:6000],
            "BIBLIOGRAPHY METADATA:\n" + bibliography[:6000],
        ]
    )


def central_results_prompt(manuscript: ExtractedManuscript) -> str:
    return """You analyze an unpublished mathematics manuscript. Do not assess proof correctness.
Identify the central theorem or central-result set using only the extracted result IDs.
Return JSON only with this shape:
{"candidates":[{"result_id":"...","role":"primary result","reason":"...","confidence":"high|medium|low","evidence":["..."]}],"uncertainties":["..."]}
If there is no theorem environment, return an empty candidates list and state that whole-paper evidence can still be used.

MANUSCRIPT
""" + _manuscript_context(manuscript)


def broad_msc_prompt(manuscript: ExtractedManuscript, broad_field_context: str, central_result_ids: Iterable[str], central_result_text: str = "") -> str:
    selected_ids = set(central_result_ids)
    results = "\n\n".join("[%s]\n%s" % (item.result_id, item.statement) for item in manuscript.theorems if item.result_id in selected_ids)
    if not results and central_result_text:
        results = central_result_text
    return """Choose the most appropriate broad MSC2020 fields for this mathematics article. Do not verify its claims.
Return JSON only: {"broad_fields":[{"code":"05","name":"...","role":"primary|secondary","confidence":"high|medium|low","evidence":["..."]}],"uncertainties":[]}
Choose at most three fields. Use only codes from the supplied list and keep evidence tied to the manuscript.

BROAD MSC OPTIONS
""" + broad_field_context + "\n\nCONFIRMED CENTRAL RESULTS\n" + results + "\n\nMANUSCRIPT\n" + _manuscript_context(manuscript)


def article_profile_prompt(
    manuscript: ExtractedManuscript,
    central_result_ids: Iterable[str],
    broad_field_context: str,
    detailed_field_context: str,
    central_result_text: str = "",
) -> str:
    selected_ids = set(central_result_ids)
    selected = [item for item in manuscript.theorems if item.result_id in selected_ids]
    result_text = "\n\n".join("[%s]\n%s" % (item.result_id, item.statement) for item in selected)
    if not result_text and central_result_text:
        result_text = central_result_text
    return """You are classifying an unpublished mathematics article. Assume its claims are genuine. Do not check or verify mathematical correctness.
Use MSC2020 codes. First choose the most appropriate broad fields from the supplied 2-digit list, then choose one primary and up to three secondary detailed codes from the supplied descendants.
Return JSON only:
{"broad_fields":[{"code":"05","name":"...","role":"primary|secondary","confidence":"high|medium|low","evidence":["..."]}],"primary_msc":{"code":"05C35","name":"...","confidence":"high|medium|low","evidence":["..."]},"secondary_msc":[],"methods":[],"keywords":[],"contribution_type":"...","claimed_improvement":"...","prerequisites":"...","technical_depth":"standard|advanced|highly specialized|unknown","conceptual_character":"...","audience":"...","audience_breadth":"narrow|subfield|field|cross-field|unknown","uncertainties":[]}
Use "unknown" rather than inventing information. Keep evidence tied to the manuscript.

BROAD MSC OPTIONS
""" + broad_field_context + "\n\nDETAILED MSC OPTIONS\n" + detailed_field_context + "\n\nCONFIRMED CENTRAL RESULTS\n" + result_text + "\n\nMANUSCRIPT\n" + _manuscript_context(manuscript)


def journal_field_profile_prompt(profile: ArticleProfile, candidate: JournalCandidate) -> str:
    articles = "\n\n".join(
        "[%s | %s]\n%s\n%s" % (item.article_id, item.year or "year unknown", item.title, item.abstract)
        for item in candidate.representative_articles
    )
    return """Create a field-local profile for a mathematics journal. Assume all supplied articles are mathematically correct. Do not use reputation, impact factor, citations, acceptance rates, or proof verification. Infer only what is supported by the supplied journal scope and representative articles.
Return JSON only:
{"typical_contributions":[],"technical_depth_range":["standard|advanced|highly specialized"],"typical_audience":"...","breadth":"narrow|subfield|field|cross-field|unknown","conceptual_character":"...","article_shape":"...","representative_article_ids":[],"confidence":"high|medium|low"}

JOURNAL
""" + "Target MSC area: " + (profile.primary_msc.code if profile.primary_msc else "unknown") + "\n" + json.dumps(candidate.to_dict(), ensure_ascii=False) + "\n\nREPRESENTATIVE ARTICLES\n" + articles


def journal_match_prompt(profile: ArticleProfile, candidates: Iterable[Mapping[str, Any]], field_profiles: Iterable[Mapping[str, Any]]) -> str:
    return """Recommend suitable mathematics journals for an unpublished research article.
Assume the article's claims and all candidate articles are mathematically correct. Do not check mathematical correctness or predict acceptance.
Use only the supplied journal data and field-local profiles. Do not use author identity, reputation, impact factor, citation count, or acceptance rate.
The candidates are pre-ranked using subject, methods, contribution type, technical depth, audience breadth, evidence quantity, and MSC specificity. Preserve that ordering unless supplied evidence clearly supports another order. Do not call a journal closely level-aligned when its technical-depth range does not contain the article's level.
Return JSON only:
{"recommendations":[{"role":"closest field-and-level match|broader-audience alternative|more specialized alternative","journal_id":"...","journal_name":"...","fit":"strong match|plausible match|weak match|insufficient information","reasons":[],"level_fit":"closely aligned|narrower than typical|broader than typical|technically different|insufficient information","representative_article_ids":[],"important_mismatch":"...","submission_emphasis":"..."}],"limitations":[]}
Return fewer than three recommendations when evidence is insufficient. Never repeat a journal.

ARTICLE PROFILE
""" + json.dumps(profile.to_dict(), ensure_ascii=False) + "\n\nCANDIDATE JOURNALS\n" + json.dumps(list(candidates), ensure_ascii=False) + "\n\nJOURNAL-FIELD PROFILES\n" + json.dumps(list(field_profiles), ensure_ascii=False)
