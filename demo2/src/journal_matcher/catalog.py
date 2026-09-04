"""SQLite-backed mathematics journal catalog.

The catalog has a broad, inexpensive registry and optional cached profiles for
one journal within one MSC area.  This keeps all-field coverage practical
without profiling thousands of journals for every manuscript.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .msc import normalize_msc_code
from .schemas import JournalCandidate, JournalFieldProfile, RepresentativeArticle


SCHEMA = """
CREATE TABLE IF NOT EXISTS journals (
    journal_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    issn_l TEXT,
    publisher TEXT,
    official_url TEXT,
    scope_url TEXT,
    scope_summary TEXT DEFAULT '',
    article_types TEXT DEFAULT '[]',
    technical_level TEXT DEFAULT 'unknown',
    audience_breadth TEXT DEFAULT 'unknown',
    active INTEGER DEFAULT 1,
    last_verified TEXT
);
CREATE TABLE IF NOT EXISTS articles (
    article_id TEXT PRIMARY KEY,
    journal_id TEXT NOT NULL REFERENCES journals(journal_id),
    doi TEXT,
    title TEXT NOT NULL,
    abstract TEXT DEFAULT '',
    year INTEGER,
    article_type TEXT DEFAULT 'research article',
    source_url TEXT
);
CREATE TABLE IF NOT EXISTS article_msc (
    article_id TEXT NOT NULL REFERENCES articles(article_id),
    msc_code TEXT NOT NULL,
    is_primary INTEGER DEFAULT 0,
    PRIMARY KEY(article_id, msc_code)
);
CREATE TABLE IF NOT EXISTS journal_msc_stats (
    journal_id TEXT NOT NULL REFERENCES journals(journal_id),
    msc_prefix TEXT NOT NULL,
    article_count INTEGER NOT NULL DEFAULT 0,
    share REAL NOT NULL DEFAULT 0,
    PRIMARY KEY(journal_id, msc_prefix)
);
CREATE TABLE IF NOT EXISTS journal_field_profiles (
    journal_id TEXT NOT NULL REFERENCES journals(journal_id),
    msc_prefix TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    generated_at TEXT,
    PRIMARY KEY(journal_id, msc_prefix)
);
CREATE INDEX IF NOT EXISTS idx_journal_msc_prefix ON journal_msc_stats(msc_prefix);
CREATE INDEX IF NOT EXISTS idx_article_msc_code ON article_msc(msc_code);
"""


def _msc_prefixes(code: str) -> Tuple[str, ...]:
    normalized = normalize_msc_code(code)
    prefixes = [normalized]
    if len(normalized) == 5 and "-" not in normalized:
        prefixes.append(normalized[:3])
    if normalized[:2] not in prefixes:
        prefixes.append(normalized[:2])
    return tuple(prefixes)


class JournalCatalog:
    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path))
        self.connection.row_factory = sqlite3.Row
        self._journal_aliases: Dict[str, str] = {}
        self.connection.executescript(SCHEMA)
        # Keep databases created by earlier demo versions usable.
        columns = {str(row[1]) for row in self.connection.execute("PRAGMA table_info(journals)")}
        for column in ("technical_level", "audience_breadth"):
            if column not in columns:
                self.connection.execute("ALTER TABLE journals ADD COLUMN %s TEXT DEFAULT 'unknown'" % column)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "JournalCatalog":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def import_json(self, path: Union[str, Path]) -> int:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise ValueError("catalog JSON must be an object")
        journals = data.get("journals", [])
        for journal in journals:
            self.upsert_journal(journal)
        for article in data.get("articles", []):
            self.upsert_article(article)
        if data.get("articles"):
            self.rebuild_statistics()
        for stat in data.get("journal_msc_stats", []):
            journal_id = self._journal_aliases.get(str(stat["journal_id"]), str(stat["journal_id"]))
            self.set_stat(journal_id, stat["msc_prefix"], int(stat.get("article_count", 0)), float(stat.get("share", 0)))
        self.connection.commit()
        return len(journals)

    def upsert_journal(self, value: Mapping[str, Any]) -> None:
        incoming_id = str(value.get("journal_id") or value.get("id") or value.get("issn_l") or value["name"])
        journal_id = incoming_id
        issn_l = str(value.get("issn_l") or "").strip()
        if issn_l:
            existing = self.connection.execute("SELECT journal_id FROM journals WHERE issn_l=?", (issn_l,)).fetchone()
            if existing:
                journal_id = str(existing[0])
        self._journal_aliases[incoming_id] = journal_id
        existing = self.connection.execute("SELECT * FROM journals WHERE journal_id=?", (journal_id,)).fetchone()
        technical_level = str(value.get("technical_level", "unknown"))
        audience_breadth = str(value.get("audience_breadth", "unknown"))
        if existing:
            if technical_level == "unknown":
                technical_level = str(existing["technical_level"] or "unknown")
            if audience_breadth == "unknown":
                audience_breadth = str(existing["audience_breadth"] or "unknown")
        self.connection.execute(
            """INSERT INTO journals(journal_id,name,issn_l,publisher,official_url,scope_url,scope_summary,article_types,technical_level,audience_breadth,active,last_verified)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(journal_id) DO UPDATE SET name=excluded.name,issn_l=excluded.issn_l,publisher=excluded.publisher,
            official_url=excluded.official_url,scope_url=excluded.scope_url,scope_summary=excluded.scope_summary,
            article_types=excluded.article_types,technical_level=excluded.technical_level,audience_breadth=excluded.audience_breadth,
            active=excluded.active,last_verified=excluded.last_verified""",
            (
                journal_id,
                str(value.get("name", journal_id)),
                issn_l or value.get("issn_l"),
                value.get("publisher"),
                value.get("official_url"),
                value.get("scope_url"),
                str(value.get("scope_summary", "")),
                json.dumps(value.get("article_types", ["research article"]), ensure_ascii=False),
                technical_level,
                audience_breadth,
                1 if value.get("active", True) else 0,
                value.get("last_verified"),
            ),
        )

    def upsert_article(self, value: Mapping[str, Any]) -> None:
        journal_id = self._journal_aliases.get(str(value["journal_id"]), str(value["journal_id"]))
        doi = str(value.get("doi") or "").strip()
        article_id = str(value.get("article_id") or value.get("id") or doi or value["title"])
        if doi:
            existing = self.connection.execute("SELECT article_id FROM articles WHERE lower(doi)=lower(?)", (doi,)).fetchone()
            if existing:
                article_id = str(existing[0])
        existing_article = self.connection.execute("SELECT * FROM articles WHERE article_id=?", (article_id,)).fetchone()
        title = str(value.get("title", "")) or (str(existing_article["title"]) if existing_article else "")
        abstract = str(value.get("abstract", "")) or (str(existing_article["abstract"]) if existing_article else "")
        year = value.get("year") if value.get("year") is not None else (existing_article["year"] if existing_article else None)
        article_type = str(value.get("article_type", "research article"))
        if article_type == "research article" and existing_article and existing_article["article_type"]:
            article_type = str(existing_article["article_type"])
        source_url = value.get("source_url") or (existing_article["source_url"] if existing_article else None)
        self.connection.execute(
            """INSERT INTO articles(article_id,journal_id,doi,title,abstract,year,article_type,source_url)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(article_id) DO UPDATE SET journal_id=excluded.journal_id,doi=excluded.doi,title=excluded.title,
            abstract=excluded.abstract,year=excluded.year,article_type=excluded.article_type,source_url=excluded.source_url""",
            (
                article_id,
                journal_id,
                doi or value.get("doi"),
                title,
                abstract,
                year,
                article_type,
                source_url,
            ),
        )
        self.connection.execute("DELETE FROM article_msc WHERE article_id=?", (article_id,))
        for index, code in enumerate(value.get("msc_codes", [])):
            self.connection.execute("INSERT OR IGNORE INTO article_msc(article_id,msc_code,is_primary) VALUES(?,?,?)", (article_id, normalize_msc_code(str(code)), 1 if index == 0 else 0))

    def set_stat(self, journal_id: str, prefix: str, count: int, share: float = 0.0) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO journal_msc_stats(journal_id,msc_prefix,article_count,share) VALUES(?,?,?,?)",
            (journal_id, normalize_msc_code(prefix), count, share),
        )

    def rebuild_statistics(self) -> None:
        """Compute exact/3-character/2-digit MSC coverage from article records."""

        self.connection.execute("DELETE FROM journal_msc_stats")
        rows = self.connection.execute(
            "SELECT a.journal_id, m.msc_code, COUNT(*) AS n FROM articles a JOIN article_msc m ON a.article_id=m.article_id WHERE lower(a.article_type) LIKE '%research%' AND lower(a.title) NOT LIKE '%republication%' AND lower(a.title) NOT LIKE '%obituary%' AND lower(a.title) NOT LIKE '%in memoriam%' GROUP BY a.journal_id,m.msc_code"
        ).fetchall()
        total_rows = self.connection.execute("SELECT journal_id, COUNT(*) FROM articles WHERE lower(article_type) LIKE '%research%' AND lower(title) NOT LIKE '%republication%' AND lower(title) NOT LIKE '%obituary%' AND lower(title) NOT LIKE '%in memoriam%' GROUP BY journal_id").fetchall()
        counts: Dict[tuple[str, str], int] = {}
        totals: Dict[str, int] = {str(row[0]): int(row[1]) for row in total_rows}
        for row in rows:
            journal_id, code, count = str(row[0]), str(row[1]), int(row[2])
            prefixes = _msc_prefixes(code)
            for prefix in prefixes:
                counts[(journal_id, prefix)] = counts.get((journal_id, prefix), 0) + count
        for (journal_id, prefix), count in counts.items():
            self.set_stat(journal_id, prefix, count, count / max(totals.get(journal_id, 1), 1))

    def find_candidates(self, msc_codes: Sequence[str], limit: int = 24) -> List[JournalCandidate]:
        codes = [normalize_msc_code(str(code)) for code in msc_codes if code]
        if not codes:
            return []
        rows: Dict[str, Dict[str, Any]] = {}
        for code in codes:
            prefixes = _msc_prefixes(code)
            for prefix in prefixes:
                matches = self.connection.execute(
                    """SELECT j.*, s.msc_prefix, s.article_count, s.share FROM journals j JOIN journal_msc_stats s ON j.journal_id=s.journal_id
                    WHERE j.active=1 AND s.msc_prefix=? ORDER BY s.article_count DESC LIMIT ?""",
                    (prefix, limit),
                ).fetchall()
                for row in matches:
                    journal_id = str(row["journal_id"])
                    tier = "exact-subfield" if prefix == code else ("subfield" if len(prefix) == 3 else "broad-field")
                    if journal_id not in rows:
                        rows[journal_id] = {"row": row, "tier": tier, "codes": set()}
                    else:
                        current_tier = rows[journal_id]["tier"]
                        tier_rank = {"exact-subfield": 0, "subfield": 1, "broad-field": 2}
                        if tier_rank[tier] < tier_rank[current_tier] or (
                            tier == current_tier
                            and int(row["article_count"] or 0) > int(rows[journal_id]["row"]["article_count"] or 0)
                        ):
                            rows[journal_id]["row"] = row
                            rows[journal_id]["tier"] = tier
                    rows[journal_id]["codes"].add(prefix)
        ordered = sorted(
            rows.values(),
            key=lambda item: (
                {"exact-subfield": 0, "subfield": 1, "broad-field": 2}[item["tier"]],
                -int(item["row"]["article_count"] or 0),
                str(item["row"]["name"]).casefold(),
                str(item["row"]["journal_id"]),
            ),
        )
        return [self._candidate(item["row"], item["tier"], sorted(item["codes"])) for item in ordered[:limit]]

    def _candidate(self, row: sqlite3.Row, tier: str, codes: List[str]) -> JournalCandidate:
        return JournalCandidate(
            journal_id=str(row["journal_id"]),
            name=str(row["name"]),
            tier=tier,
            matching_codes=codes,
            official_url=row["official_url"],
            scope_summary=str(row["scope_summary"] or ""),
            representative_articles=self.representative_articles(str(row["journal_id"]), max(codes, key=len) if codes else "", 8),
            article_count=int(row["article_count"] or 0),
            matching_share=float(row["share"] or 0.0),
            technical_level=str(row["technical_level"] or "unknown"),
            audience_breadth=str(row["audience_breadth"] or "unknown"),
        )

    def representative_articles(self, journal_id: str, msc_prefix: str, limit: int = 8) -> List[RepresentativeArticle]:
        prefix = normalize_msc_code(msc_prefix)
        rows = self.connection.execute(
            """SELECT DISTINCT a.* FROM articles a JOIN article_msc m ON a.article_id=m.article_id
            WHERE a.journal_id=? AND m.msc_code LIKE ? AND lower(a.article_type) LIKE '%research%'
            ORDER BY a.year DESC NULLS LAST, a.article_id""",
            (journal_id, prefix + "%"),
        ).fetchall()
        # Some providers label reprints and memorial pieces as research.  Do
        # not let those become the examples used to infer a journal's level.
        excluded = ("republication", "obituary", "in memoriam", "the life and work")
        rows = [row for row in rows if not any(token in str(row["title"]).lower() for token in excluded)][:limit]
        return [
            RepresentativeArticle(
                article_id=str(row["article_id"]),
                title=str(row["title"]),
                year=int(row["year"]) if row["year"] is not None else None,
                abstract=str(row["abstract"] or ""),
                msc_codes=[str(item[0]) for item in self.connection.execute("SELECT msc_code FROM article_msc WHERE article_id=?", (row["article_id"],)).fetchall()],
                doi=row["doi"],
                source_url=row["source_url"],
                article_type=str(row["article_type"] or "research article"),
            )
            for row in rows
        ]

    def get_field_profile(self, journal_id: str, msc_prefix: str) -> Optional[JournalFieldProfile]:
        row = self.connection.execute("SELECT profile_json FROM journal_field_profiles WHERE journal_id=? AND msc_prefix=?", (journal_id, msc_prefix)).fetchone()
        if not row:
            return None
        value = json.loads(row[0])
        return JournalFieldProfile(journal_id=journal_id, msc_prefix=msc_prefix, **value)

    def save_field_profile(self, profile: JournalFieldProfile, generated_at: str = "") -> None:
        value = profile.to_dict().copy()
        value.pop("journal_id", None)
        value.pop("msc_prefix", None)
        self.connection.execute(
            "INSERT OR REPLACE INTO journal_field_profiles(journal_id,msc_prefix,profile_json,generated_at) VALUES(?,?,?,?)",
            (profile.journal_id, profile.msc_prefix, json.dumps(value, ensure_ascii=False), generated_at),
        )
        self.connection.commit()

    def counts(self) -> Dict[str, int]:
        return {
            "journals": int(self.connection.execute("SELECT COUNT(*) FROM journals WHERE active=1").fetchone()[0]),
            "articles": int(self.connection.execute("SELECT COUNT(*) FROM articles").fetchone()[0]),
            "msc_codes": int(self.connection.execute("SELECT COUNT(DISTINCT msc_code) FROM article_msc").fetchone()[0]),
        }
