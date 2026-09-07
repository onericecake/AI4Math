"""Hybrid article/scope retrieval with explicit primary-field features."""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Protocol, Sequence

from .corpus import eligible_research
from .schemas import ArticleProfile, JournalCandidate, RepresentativeArticle
from .rerank import default_contributions


STOP = set("a an and are as at be by for from has have in into is it its of on or our that the their these this to using we were which with paper article result results mathematics mathematical new unknown".split())


def tokens(text: str) -> list[str]:
    words = re.findall(r"[^\W\d_][\w-]*", text.casefold(), re.UNICODE)
    # Only conservative inflection normalization; preserve mathematical stems.
    return [w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "is", "us")) else w for w in words if len(w) > 2 and w not in STOP]


def profile_text(profile: ArticleProfile) -> str:
    parts = [profile.retrieval_text] + profile.keywords + profile.methods + [profile.contribution_type, profile.claimed_improvement]
    parts += [str(r.get("statement", "")) for r in profile.central_results]
    return " ".join(str(p).strip() for p in parts if str(p).strip() and str(p).strip() != "unknown")


class BM25:
    def __init__(self, documents: Sequence[str]):
        self.lengths = [len(tokens(d)) for d in documents]
        self.average = sum(self.lengths) / max(len(documents), 1)
        self.postings = defaultdict(list)
        for index, document in enumerate(documents):
            for token, count in Counter(tokens(document)).items():
                self.postings[token].append((index, count))
        self.count = len(documents)

    def scores(self, query: str) -> dict[int, float]:
        scores = defaultdict(float)
        for token in set(tokens(query)):
            posting = self.postings.get(token, [])
            idf = math.log(1 + (self.count - len(posting) + 0.5) / (len(posting) + 0.5))
            for index, count in posting:
                norm = 1.2 * (0.25 + 0.75 * self.lengths[index] / max(self.average, 1))
                scores[index] += idf * count * 2.2 / (count + norm)
        return dict(scores)


class TextEncoder(Protocol):
    identity: str

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class SentenceTransformerEncoder:
    """Optional local semantic backend. Construction may download the model."""
    def __init__(self, name: str, revision: str):
        if not revision or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
            raise ValueError("A pinned 40-character embedding model commit is required for reproducible caches")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError("Semantic retrieval requires the optional 'semantic' extra") from error
        self.identity = "sentence-transformers:" + name + "@" + revision
        self.encoder = SentenceTransformer(name, revision=revision, trust_remote_code=False)

    def encode(self, texts):
        return self.encoder.encode(list(texts), batch_size=64, normalize_embeddings=True, show_progress_bar=False).tolist()


def unit_vector(values):
    values = [float(x) for x in values]
    if not values or not all(math.isfinite(x) for x in values):
        raise ValueError("Embedding vectors must be nonempty and finite")
    norm = math.sqrt(sum(x * x for x in values))
    return [x / norm for x in values] if norm else values


class CachedEncoder:
    def __init__(self, catalog, encoder: TextEncoder):
        self.catalog, self.encoder = catalog, encoder
        self.identity = encoder.identity

    def encode(self, texts):
        keys = [hashlib.sha256((self.identity + "\n" + t).encode()).hexdigest() for t in texts]
        vectors, missing = {}, {}
        for key, text in zip(keys, texts):
            row = self.catalog.connection.execute("SELECT vector_json FROM text_embeddings WHERE cache_key=?", (key,)).fetchone()
            if row:
                vectors[key] = unit_vector(json.loads(row[0]))
            else:
                missing[key] = text
        missing_keys = list(missing)
        for offset in range(0, len(missing_keys), 64):
            batch = missing_keys[offset:offset + 64]
            encoded = self.encoder.encode([missing[key] for key in batch])
            if len(encoded) != len(batch):
                raise ValueError("Encoder returned the wrong number of vectors")
            for key, vector in zip(batch, encoded):
                vectors[key] = unit_vector(vector)
                self.catalog.connection.execute("INSERT OR REPLACE INTO text_embeddings VALUES (?,?)", (key, json.dumps(vectors[key])))
        self.catalog.connection.commit()
        values = [vectors[key] for key in keys]
        if values and len({len(v) for v in values}) != 1:
            raise ValueError("Encoder dimensions changed; use a distinct model identity")
        return values


def msc_similarity(query: str, codes: Sequence[str]) -> float:
    # Broad coverage is positive evidence. Missing detailed tags do not imply
    # poor fit. Primary and secondary queries are scored separately.
    return max((1.0 if c == query and len(c) == 5 else 0.9 if len(c) >= 3 and c[:3] == query[:3]
                else 0.7 if c[:2] == query[:2] else 0.0 for c in codes), default=0.0)


class FieldDistributions:
    """Shrink observed field shares toward a corpus background distribution.

    A single sampled paper must not establish that a journal specializes in its
    field. Imported population shares and local sample shares retain separate
    denominators; detailed tags are never added to their own broad parents.
    """
    def __init__(self, stats, prior_strength=50):
        self.prior_strength = prior_strength
        self.by_journal = defaultdict(dict)
        for stat in stats:
            if len(stat["msc_prefix"]) == 2 and stat["article_count"] > 0:
                self.by_journal[stat["journal_id"]][stat["msc_prefix"]] = stat
        self.totals = {}
        background = defaultdict(list)
        for journal_id, fields in self.by_journal.items():
            for source in {s.get("source", "imported") for s in fields.values()}:
                rows = [s for s in fields.values() if s.get("source", "imported") == source]
                estimates = [s["article_count"] / s["share"] for s in rows if s.get("share", 0) > 0]
                total = max(max(s["article_count"] for s in rows), statistics.median(estimates) if estimates else sum(s["article_count"] for s in rows))
                self.totals[journal_id, source] = total
            for field, stat in fields.items():
                background[field].append(stat["article_count"] / self.totals[journal_id, stat.get("source", "imported")])
        # Equal journal weighting keeps a large publisher from setting the prior.
        count = max(len(self.by_journal), 1)
        self.background = {field: sum(values) / count for field, values in background.items()}

    def focus(self, journal_id, code):
        stat = self.by_journal[journal_id].get(code[:2])
        if not stat:
            return 0.0
        total = self.totals[journal_id, stat.get("source", "imported")]
        prior = self.background.get(code[:2], 0)
        share = (stat["article_count"] + self.prior_strength * prior) / (total + self.prior_strength)
        # Compress the scale so broad journals remain viable when their text
        # evidence fits. This is a ranking feature, not a venue probability.
        return math.sqrt(min(1.0, share))


class HybridRetriever:
    def __init__(self, catalog, encoder: TextEncoder | None = None, neighbors=100, strategy="hybrid"):
        if strategy not in {"hybrid", "focused"}:
            raise ValueError("Unknown hybrid retrieval strategy")
        self.catalog = catalog
        self.strategy = strategy
        self.encoder = CachedEncoder(catalog, encoder) if encoder else None
        self.neighbors = neighbors
        self.revision = -1

    def _refresh(self):
        if self.revision == self.catalog.revision:
            return
        data = self.catalog.export_data()
        self.journals = {j["journal_id"]: j for j in data["journals"] if j.get("active", True)}
        self.fields = FieldDistributions([s for s in data.get("journal_msc_stats", []) if s["journal_id"] in self.journals]) if self.strategy == "focused" else None
        self.articles = {a["article_id"]: a for a in data["articles"] if a["journal_id"] in self.journals and eligible_research(a)}
        self.docs, self.doc_keys, self.doc_kinds = [], [], []
        self.by_journal = defaultdict(list)
        for article in self.articles.values():
            self.by_journal[article["journal_id"]].append(article)
            main_results = " ".join(str(r.get("statement", "")) for r in article.get("central_results", []) if isinstance(r, dict))
            self.docs.append("\n".join([article["title"], article.get("abstract", ""), article.get("introduction", "")[:6000], main_results[:6000]]))
            self.doc_keys.append((article["journal_id"], article["article_id"]))
            self.doc_kinds.append("article")
        for journal in self.journals.values():
            scope = journal.get("scope_summary", "")
            if scope.startswith("Indexed mathematics journal."):
                scope = ""  # Registry boilerplate is not editorial scope text.
            self.docs.append(journal["name"] + "\n" + scope)
            self.doc_keys.append((journal["journal_id"], None))
            self.doc_kinds.append("scope" if scope.strip() else "name")
        self.lexical = BM25(self.docs)
        self.vectors = self.encoder.encode(self.docs) if self.encoder and self.docs else []
        self.revision = self.catalog.revision

    def retrieve(self, profile: ArticleProfile, limit=50) -> list[JournalCandidate]:
        if limit <= 0:
            return []
        self._refresh()
        query = profile_text(profile)
        survey_query = any(t in profile.contribution_type.casefold() for t in ("survey", "review"))
        def allows_type(journal_id):
            kinds = " ".join(self.journals[journal_id].get("article_types", [])).casefold()
            return survey_query or not kinds or "research" in kinds or kinds in {"article", "journal-article", "unknown"}
        primary = profile.primary_msc.code if profile.primary_msc else ""
        secondary = [c.code for c in profile.secondary_msc]
        codes = ([primary] if primary else []) + secondary + [c.code for c in profile.broad_fields]
        candidates = {c.journal_id: c for c in self.catalog.find_candidates(codes, limit=None, include_articles=False) if c.journal_id in self.journals and allows_type(c.journal_id)}
        lexical = self.lexical.scores(query)
        semantic = {}
        if self.vectors and tokens(query):
            vector = self.encoder.encode([query])[0]
            if len(vector) != len(self.vectors[0]):
                raise ValueError("Query and corpus embedding dimensions differ")
            semantic = {i: sum(x * y for x, y in zip(vector, v)) for i, v in enumerate(self.vectors)}
        routes = {"lexical": lexical, "semantic": semantic}
        top_docs = {name: sorted((i for i in scores if scores[i] > 0), key=lambda i: (-scores[i], self.doc_keys[i][0], self.doc_keys[i][1] or ""))[:self.neighbors] for name, scores in routes.items()}
        route_journals = {name: {self.doc_keys[i][0] for i in indexes} for name, indexes in top_docs.items()}
        for journal_id in set().union(*route_journals.values()):
            if not allows_type(journal_id):
                continue
            if journal_id not in candidates:
                j = self.journals[journal_id]
                candidates[journal_id] = JournalCandidate(journal_id, j["name"], "text-match", official_url=j.get("official_url"),
                    scope_summary=j.get("scope_summary", ""), technical_level=j.get("technical_level", "unknown"), audience_breadth=j.get("audience_breadth", "unknown"),
                    scope_url=j.get("scope_url"), scope_breadth=j.get("scope_breadth", "unknown"), editorial_evidence=j.get("editorial_evidence", []))
        lex_by_journal, sem_by_journal, article_scores = defaultdict(float), defaultdict(float), defaultdict(float)
        article_lexical, article_semantic = defaultdict(list), defaultdict(list)
        maximum = max(lexical.values(), default=1.0) or 1.0
        for i, (journal_id, article_id) in enumerate(self.doc_keys):
            lex = lexical.get(i, 0.0) / maximum
            sem = max(0, semantic.get(i, 0.0))
            if self.strategy == "hybrid":
                lex_by_journal[journal_id] = max(lex_by_journal[journal_id], lex)
                sem_by_journal[journal_id] = max(sem_by_journal[journal_id], sem)
            if article_id:
                article_lexical[journal_id].append(lex)
                article_semantic[journal_id].append(sem)
                article = self.articles[article_id]
                article_scores[article_id] = .55 * lex + .2 * sem + .2 * msc_similarity(primary, article["msc_codes"]) if primary else .75 * lex + .25 * sem
            elif self.strategy == "focused":
                # A journal name is a discovery hint, not the equivalent of
                # a matching abstract or a substantive editorial scope.
                weight = .25 if self.doc_kinds[i] == "name" else 1.0
                lex_by_journal[journal_id] = max(lex_by_journal[journal_id], weight * lex)
                sem_by_journal[journal_id] = max(sem_by_journal[journal_id], weight * sem)
        for groups, destination in ((article_lexical, lex_by_journal), (article_semantic, sem_by_journal)):
            for journal_id, values in groups.items():
                best = sorted(values, reverse=True)[:3]
                # Fixed-size mean: extra irrelevant papers cannot dilute fit,
                # while independent corroboration beats one isolated example.
                if self.strategy == "focused":
                    destination[journal_id] = max(destination[journal_id], .75 * best[0] + .25 * sum(best) / 3)
        result = []
        for candidate in candidates.values():
            journal_id = candidate.journal_id
            primary_score = msc_similarity(primary, candidate.matching_codes) if primary else max((msc_similarity(c.code, candidate.matching_codes) for c in profile.broad_fields), default=0)
            secondary_score = sum(msc_similarity(c, candidate.matching_codes) for c in secondary) / max(len(secondary), 1)
            # Select evidence by query relevance, using year and ID solely to
            # break equal-relevance ties. Prefer distinct years when close.
            available = self.by_journal[journal_id]
            selected, years = [], set()
            remaining = [a for a in available if article_scores[a["article_id"]] > 0 or
                         any(msc_similarity(c, a["msc_codes"]) > 0 for c in codes)]
            while remaining and len(selected) < 8:
                article = max(remaining, key=lambda a: (article_scores[a["article_id"]] + .01 * (a.get("year") not in years), a.get("year") or 0, a["article_id"]))
                selected.append(article)
                years.add(article.get("year"))
                remaining.remove(article)
            evidence = [RepresentativeArticle(**{k: a.get(k) for k in ("article_id", "title", "year", "abstract", "msc_codes", "doi", "source_url", "article_type")},
                                              introduction=a.get("introduction", "")[:6000], central_results=a.get("central_results", [])[:8],
                                              authors=a.get("authors", []), license=a.get("license", ""), license_url=a.get("license_url", "")) for a in selected]
            evidence_prefix = candidate.evidence_msc_prefix
            if evidence and not all(any(code.startswith(evidence_prefix) for code in a.msc_codes) for a in evidence):
                evidence_prefix = primary[:2] if primary and all(any(code.startswith(primary[:2]) for code in a.msc_codes) for a in evidence) else ""
            support = min(1.0, math.log1p(sum(bool(a.abstract) for a in evidence)) / math.log1p(20))
            features = {"primary_msc": primary_score, "secondary_msc": secondary_score,
                        "lexical": lex_by_journal[journal_id], "semantic": sem_by_journal[journal_id],
                        "abstract_support": support, "semantic_available": float(self.encoder is not None)}
            if self.strategy == "focused":
                features.update(primary_focus=self.fields.focus(journal_id, primary) if primary else max((self.fields.focus(journal_id, c.code) for c in profile.broad_fields), default=0),
                                secondary_focus=sum(self.fields.focus(journal_id, c) for c in secondary) / max(len(secondary), 1), focus_available=1.0)
            sources = (["msc"] if candidate.matching_codes else []) + [name for name, ids in route_journals.items() if journal_id in ids]
            components = default_contributions(features)
            result.append(replace(candidate, representative_articles=evidence, evidence_msc_prefix=evidence_prefix, retrieval_scores=features,
                                  retrieval_sources=sources, match_score=sum(components.values()), score_components=components))
        return sorted(result, key=lambda c: (-c.match_score, c.journal_id))[:limit]
