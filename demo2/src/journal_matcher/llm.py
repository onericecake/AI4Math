from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Protocol


_KEYWORD_STOPWORDS = {
    "article",
    "field",
    "journal",
    "mathematics",
    "problem",
    "problems",
    "research",
    "result",
    "results",
    "theorem",
    "theory",
    "unknown",
}


def _keyword_tokens(text: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        if token.startswith("combinator"):
            token = "combinator"
        elif token.startswith("graph"):
            token = "graph"
        if len(token) >= 4 and token not in _KEYWORD_STOPWORDS:
            tokens.add(token)
    return tokens


class JSONLanguageModel(Protocol):
    def complete_json(self, prompt: str) -> Any:
        ...


def parse_json_response(text: str) -> Any:
    """Parse common JSON responses, including accidental Markdown fences."""

    value = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)```", value, re.I | re.S)
    if fenced:
        value = fenced.group(1).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        starts = [index for index, char in enumerate(value) if char in "[{]"]
        for start in starts:
            try:
                return json.JSONDecoder().raw_decode(value[start:])[0]
            except json.JSONDecodeError:
                continue
    raise ValueError("language model returned invalid JSON")


class OpenAIJSONModel:
    """Thin Responses API adapter for the journal matcher."""

    def __init__(self, model: str, max_output_tokens: int = 2400, client: Optional[Any] = None) -> None:
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as error:
                raise RuntimeError("The OpenAI SDK is not installed. Run: pip install -e .") from error
            client = OpenAI()
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens

    def complete_json(self, prompt: str) -> Any:
        for attempt in range(2):
            response = self.client.responses.create(
                model=self.model,
                instructions="You are a careful mathematics editorial analyst. Return only valid JSON.",
                input=prompt if attempt == 0 else prompt + "\nYour previous response was not valid JSON. Return valid JSON only.",
                max_output_tokens=self.max_output_tokens,
                store=False,
            )
            try:
                return parse_json_response(response.output_text)
            except ValueError:
                if attempt == 1:
                    raise
        raise ValueError("language model returned invalid JSON")


class HeuristicJSONModel:
    """Deterministic, offline smoke-test model.

    This is intentionally not a replacement for an editorial language model.
    It allows the complete extraction/catalog/report path to be tested without
    an API key and is useful for CI fixtures.
    """

    _BROAD = {
        "contact": ("53", "Differential geometry"),
        "symplectic": ("53", "Differential geometry"),
        "lagrangian": ("53", "Differential geometry"),
        "legendrian": ("57", "Manifolds and cell complexes"),
        "knot": ("57", "Manifolds and cell complexes"),
        "ruling polynomial": ("57", "Manifolds and cell complexes"),
        "cluster algebra": ("13", "Commutative algebra"),
        "graph": ("05", "Combinatorics"),
        "prime": ("11", "Number theory"),
    }

    def complete_json(self, prompt: str) -> Any:
        lower = prompt.lower()
        if "identify the central theorem" in lower:
            ids = [item.strip() for item in re.findall(r"\[([^\]|]+)\s*\|", prompt)]
            preferred = [item for item in ids if item.startswith("thm:") or item.startswith("intro:prop:")]
            order = ["thm:main", "thm:non-orientable", "intro:prop:notsmooth", "thm:aug"]
            selected = [item for item in order if item in preferred]
            selected += [item for item in preferred if item not in selected]
            selected = selected[:4] or ids[:1]
            return {"candidates": [{"result_id": item, "role": "primary result" if index == 0 else "central result", "reason": "Prominent labeled result in the extracted manuscript.", "confidence": "medium", "evidence": ["Extracted theorem label and introduction context."]} for index, item in enumerate(selected)], "uncertainties": ["Offline heuristic; author confirmation is required."]}
        if "choose the most appropriate broad msc" in lower:
            fields = []
            seen = set()
            for key, (code, name) in self._BROAD.items():
                if key in lower and code not in seen:
                    fields.append({"code": code, "name": name, "role": "primary" if not fields else "secondary", "confidence": "medium", "evidence": ["Keyword evidence in extracted manuscript."]})
                    seen.add(code)
            return {"broad_fields": fields[:3], "uncertainties": ["Offline heuristic; detailed MSC confirmation is required."]}
        if "classifying an unpublished mathematics article" in lower:
            manuscript_text = lower.rsplit("\n\nmanuscript\n", 1)[-1]
            if any(key in manuscript_text for key in ("legendrian", "symplectic", "contact", "lagrangian", "ruling polynomial")):
                return {
                    "broad_fields": [
                        {"code": "53", "name": "Differential geometry", "role": "primary"},
                        {"code": "57", "name": "Manifolds and cell complexes", "role": "secondary"},
                        {"code": "13", "name": "Commutative algebra", "role": "secondary"},
                    ],
                    "primary_msc": {
                        "code": "53D42",
                        "name": "Symplectic field theory; contact homology",
                        "confidence": "medium",
                        "evidence": ["Legendrian, contact, and symplectic terminology in the title and introduction."],
                    },
                    "secondary_msc": [
                        {"code": "57K10", "name": "Knot theory", "confidence": "medium", "evidence": ["The manuscript constructs Legendrian knots and links."]},
                        {"code": "13F60", "name": "Cluster algebras", "confidence": "medium", "evidence": ["The manuscript discusses cluster structures on augmentation varieties."]},
                    ],
                    "methods": ["Legendrian contact topology", "ruling polynomials", "augmentation varieties", "exact Lagrangian fillings", "gauge-theoretic obstructions"],
                    "contribution_type": "classification and explicit constructions",
                    "claimed_improvement": "Characterizes all graded and ungraded ruling polynomials and constructs realizations.",
                    "prerequisites": "Specialist knowledge of contact and symplectic topology, Legendrian knot theory, and low-dimensional topology.",
                    "technical_depth": "highly specialized",
                    "conceptual_character": "Several structural classification theorems with explicit constructions and geometric applications.",
                    "audience": "Researchers in contact and symplectic topology, Legendrian knot theory, and low-dimensional topology.",
                    "audience_breadth": "subfield",
                    "uncertainties": ["This is an offline heuristic profile; verify MSC codes and contribution level with an expert."],
                }
            if "graph" in manuscript_text:
                return {
                    "broad_fields": [
                        {
                            "code": "05",
                            "name": "Combinatorics",
                            "role": "primary",
                            "confidence": "medium",
                            "evidence": ["Graph-theoretic terminology in the abstract and central result."],
                        }
                    ],
                    "primary_msc": {
                        "code": "05C35",
                        "name": "Extremal problems in graph theory",
                        "confidence": "medium",
                        "evidence": ["The manuscript states an improved bound for a family of graphs."],
                    },
                    "secondary_msc": [],
                    "methods": ["extremal graph theory"],
                    "contribution_type": "improvement of a bound",
                    "claimed_improvement": "Improves an extremal estimate for a family of graphs.",
                    "prerequisites": "Graph theory and extremal combinatorics.",
                    "technical_depth": "unknown",
                    "conceptual_character": "A quantitative extremal result.",
                    "audience": "Researchers in graph theory and combinatorics.",
                    "audience_breadth": "subfield",
                    "uncertainties": ["This is an offline heuristic profile; verify the detailed MSC code and contribution level with an expert."],
                }
            return {"broad_fields": [], "primary_msc": None, "secondary_msc": [], "methods": [], "contribution_type": "unknown", "technical_depth": "unknown", "audience_breadth": "unknown", "uncertainties": ["Offline heuristic found no supported keywords."]}
        if "create a field-local profile" in lower:
            ids = re.findall(r'"article_id"\s*:\s*"([^"]+)"', prompt)
            return {"typical_contributions": ["specialized research theorems", "new constructions"], "technical_depth_range": ["advanced", "highly specialized"], "typical_audience": "Specialists in the relevant MSC area", "breadth": "subfield", "conceptual_character": "Technical and conceptual research results", "article_shape": "standard research article", "representative_article_ids": ids[:8], "confidence": "low"}
        if "recommend suitable mathematics journals" in lower:
            candidates = []
            try:
                raw_candidates = prompt.split("CANDIDATE JOURNALS\n", 1)[1].split("\n\nJOURNAL-FIELD PROFILES", 1)[0]
                candidates = json.loads(raw_candidates)
            except (IndexError, json.JSONDecodeError):
                candidates = [{"journal_id": item[0], "name": item[1], "representative_articles": []} for item in re.findall(r'"journal_id"\s*:\s*"([^"]+)"\s*,\s*"name"\s*:\s*"([^"]+)"', prompt)]
            try:
                raw_profile = prompt.split("ARTICLE PROFILE\n", 1)[1].split("\n\nCANDIDATE JOURNALS", 1)[0]
                article_profile = json.loads(raw_profile)
                profile_text = " ".join(
                    [
                        str(item.get("name", ""))
                        for item in article_profile.get("broad_fields", []) + article_profile.get("secondary_msc", [])
                        if isinstance(item, dict)
                    ]
                    + [str((article_profile.get("primary_msc") or {}).get("name", ""))]
                    + [str(item) for item in article_profile.get("methods", [])]
                    + [
                        str(article_profile.get(key, ""))
                        for key in ("contribution_type", "claimed_improvement", "conceptual_character", "audience")
                    ]
                )
                article_keywords = _keyword_tokens(profile_text)
            except (AttributeError, IndexError, json.JSONDecodeError, TypeError):
                article_keywords = set()

            def relevance(candidate):
                name_keywords = _keyword_tokens(str(candidate.get("name", "")))
                evidence_text = str(candidate.get("scope_summary", ""))
                evidence_text += " " + " ".join(
                    str(item.get("title", "")) + " " + str(item.get("abstract", ""))
                    for item in candidate.get("representative_articles", [])
                    if isinstance(item, dict)
                )
                evidence_keywords = _keyword_tokens(evidence_text)
                tier_bonus = {"exact-subfield": 3, "subfield": 2, "broad-field": 1}.get(str(candidate.get("tier", "")), 0)
                return 8 * len(article_keywords & name_keywords) + 3 * len(article_keywords & evidence_keywords) + tier_bonus

            ranked = [
                candidate
                for _, candidate in sorted(
                    enumerate(candidates),
                    key=lambda item: (-relevance(item[1]), item[0]),
                )
            ]
            recommendations = []
            roles = ["closest field-and-level match", "broader-audience alternative", "more specialized alternative"]
            selected = []
            for candidate in ranked:
                if candidate.get("journal_id") not in {item.get("journal_id") for item in selected}:
                    selected.append(candidate)
                if len(selected) == 3:
                    break
            for index, candidate in enumerate(selected):
                journal_id, name = str(candidate.get("journal_id", "")), str(candidate.get("name", ""))
                representatives = [str(item.get("article_id")) for item in candidate.get("representative_articles", []) if isinstance(item, dict) and item.get("article_id")]
                matching_codes = [str(code) for code in candidate.get("matching_codes", []) if code]
                reasons = ["The catalog contains recent publications in the confirmed MSC area."]
                if matching_codes:
                    reasons.append("Matching catalog codes: " + ", ".join(matching_codes) + ".")
                if representatives:
                    reasons.append("Representative articles are available for field-level comparison.")
                recommendations.append({"role": roles[index], "journal_id": journal_id, "journal_name": name, "fit": "plausible match" if matching_codes else "insufficient information", "reasons": reasons, "level_fit": "insufficient information", "representative_article_ids": representatives[:3], "important_mismatch": "Offline smoke-test mode does not assess the journal's current scope, level, or submission policies.", "submission_emphasis": "State the central result, confirmed MSC classification, and contribution relative to the cited literature."})
            return {"recommendations": recommendations, "limitations": ["Offline heuristic smoke test; replace with an LLM for substantive recommendations."]}
        return {}
