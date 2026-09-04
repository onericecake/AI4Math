from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Protocol


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
            # Restrict marker parsing to manuscript evidence; the JSON schema
            # itself contains a ``high|medium|low`` pipe-separated example.
            manuscript_context = prompt.split("MANUSCRIPT\n", 1)[-1]
            ids = [
                result_id.strip()
                for result_id, marker in re.findall(r"\[([^\]|]+)\s*\|\s*([^\]]+)\]", manuscript_context)
                if not marker.strip().lower().startswith("level")
            ]
            preferred = [item for item in ids if item.startswith("thm:") or item.startswith("intro:prop:")]
            order = ["thm:main", "thm:non-orientable", "intro:prop:notsmooth", "thm:aug"]
            selected = [item for item in order if item in preferred]
            selected += [item for item in preferred if item not in selected]
            selected = selected[:4] or ids[:1]
            return {"candidates": [{"result_id": item, "role": "primary result" if index == 0 else "central result", "reason": "Prominent labeled result in the extracted manuscript.", "confidence": "medium", "evidence": ["Extracted theorem label and introduction context."]} for index, item in enumerate(selected)], "uncertainties": ["Offline heuristic; whole-paper classification has limited subject coverage."]}
        if "choose the most appropriate broad msc" in lower:
            fields = []
            seen = set()
            for key, (code, name) in self._BROAD.items():
                if key in lower and code not in seen:
                    fields.append({"code": code, "name": name, "role": "primary" if not fields else "secondary", "confidence": "medium", "evidence": ["Keyword evidence in extracted manuscript."]})
                    seen.add(code)
            return {"broad_fields": fields[:3], "uncertainties": ["Offline heuristic; detailed MSC confirmation is required."]}
        if "classifying an unpublished mathematics article" in lower:
            if any(key in lower for key in ("legendrian", "symplectic", "contact", "lagrangian", "ruling polynomial")):
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
                    "uncertainties": ["This is an offline heuristic profile with limited subject coverage."],
                }
            if any(key in lower for key in ("extremal graph", "graph", "graph bound", "graph family")):
                return {
                    "broad_fields": [{"code": "05", "name": "Combinatorics", "role": "primary"}],
                    "primary_msc": {
                        "code": "05C35",
                        "name": "Extremal graph theory",
                        "confidence": "medium",
                        "evidence": ["Graph and extremal-bound terminology appears in the manuscript."],
                    },
                    "secondary_msc": [],
                    "methods": ["extremal methods", "graph-theoretic arguments"],
                    "keywords": ["graph", "extremal", "bound"],
                    "contribution_type": "improvement of a bound",
                    "claimed_improvement": "Improves an extremal estimate for a graph family.",
                    "prerequisites": "Graph theory and extremal combinatorics.",
                    "technical_depth": "advanced",
                    "conceptual_character": "A focused extremal graph-theory result.",
                    "audience": "Researchers in combinatorics and graph theory.",
                    "audience_breadth": "subfield",
                    "uncertainties": ["This is an offline heuristic profile with limited subject coverage."],
                }
            return {"broad_fields": [], "primary_msc": None, "secondary_msc": [], "methods": [], "contribution_type": "unknown", "technical_depth": "unknown", "audience_breadth": "unknown", "uncertainties": ["Offline heuristic found no supported keywords."]}
        if "create a field-local profile" in lower:
            ids = re.findall(r'"article_id"\s*:\s*"([^"]+)"', prompt)
            return {"typical_contributions": ["specialized research theorems", "new constructions"], "technical_depth_range": ["advanced", "highly specialized"], "typical_audience": "Specialists in the relevant MSC area", "breadth": "subfield", "conceptual_character": "Technical and conceptual research results", "article_shape": "standard research article", "representative_article_ids": ids[:8], "confidence": "low"}
        if "recommend suitable mathematics journals" in lower:
            candidates = []
            profile = {}
            try:
                raw_candidates = prompt.split("CANDIDATE JOURNALS\n", 1)[1].split("\n\nJOURNAL-FIELD PROFILES", 1)[0]
                candidates = json.loads(raw_candidates)
                raw_profile = prompt.split("ARTICLE PROFILE\n", 1)[1].split("\n\nCANDIDATE JOURNALS", 1)[0]
                profile = json.loads(raw_profile)
            except (IndexError, json.JSONDecodeError):
                candidates = [{"journal_id": item[0], "name": item[1], "representative_articles": []} for item in re.findall(r'"journal_id"\s*:\s*"([^"]+)"\s*,\s*"name"\s*:\s*"([^"]+)"', prompt)]
            profile_terms = []
            for key in ("keywords", "methods"):
                profile_terms.extend(str(item) for item in profile.get(key, []) if item)
            for key in ("contribution_type", "conceptual_character", "audience"):
                profile_terms.append(str(profile.get(key, "")))
            query = set(re.findall(r"[a-z][a-z0-9-]{2,}", " ".join(profile_terms).lower()))
            def relevance(candidate):
                corpus = " ".join(
                    [str(candidate.get("name", "")), str(candidate.get("scope_summary", ""))]
                    + [str(item.get("title", "")) + " " + str(item.get("abstract", "")) for item in candidate.get("representative_articles", []) if isinstance(item, dict)]
                )
                terms = set(re.findall(r"[a-z][a-z0-9-]{2,}", corpus.lower()))
                score = 4 * len(query & terms) + 2 * float(candidate.get("match_score", 0.0))
                if str(candidate.get("technical_level", "unknown")).lower() == str(profile.get("technical_depth", "unknown")).lower():
                    score += 2
                return score
            ranked = sorted(candidates, key=lambda item: (-relevance(item), -float(item.get("match_score", 0.0)), str(item.get("name", "")).casefold()))
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
                level_distance = candidate.get("level_distance")
                level_fit = "closely aligned" if index == 0 or level_distance == 0 else "insufficient information"
                subject = str(profile.get("primary_msc", {}).get("name", "the confirmed field")) if isinstance(profile.get("primary_msc"), dict) else "the confirmed field"
                recommendations.append({"role": roles[index], "journal_id": journal_id, "journal_name": name, "fit": "strong match" if index == 0 else "plausible match", "reasons": ["The catalog contains publications in %s." % subject, "The journal's supplied scope and article metadata overlap the manuscript profile."], "level_fit": level_fit, "representative_article_ids": representatives[:3], "important_mismatch": "Offline smoke-test model has limited journal-scope coverage and does not estimate acceptance.", "submission_emphasis": "Emphasize the article's stated contribution, methods, and intended specialist audience."})
            return {"recommendations": recommendations, "limitations": ["Offline heuristic smoke test; replace with an LLM for substantive recommendations."]}
        return {}
