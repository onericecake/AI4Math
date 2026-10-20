"""Small, optional file library shared across mathematical problems."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


MAX_IMPORT_CHARS = 60_000
MAX_RECORD_BYTES = 250_000
STOPWORDS = {
    "about", "all", "and", "are", "argument", "assumptions", "case", "claim",
    "completion", "criteria", "define", "definitions", "every", "for", "from",
    "give", "has", "have", "into", "let", "must", "not", "permitted",
    "problem", "proof", "prove", "result", "show", "some", "such", "that",
    "the", "theorem", "there", "this",
    "using", "valid", "where", "with",
}


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_id(body: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def make_record(
    *, kind: str, status: str, statement: str, assumptions: list[str],
    argument: str, dependencies: list[dict[str, Any]], source_problem_sha256: str,
    source_problem_path: str, source_run: str, source_model: str,
) -> dict[str, Any]:
    if kind not in {"claim", "solution"} or status not in {"unverified", "model_checked"}:
        raise ValueError("invalid library kind or status")
    body = {
        "schema_version": 1,
        "kind": kind,
        "status": status,
        "statement": statement,
        "assumptions": assumptions,
        "argument": argument,
        "dependencies": dependencies,
        "source_problem_sha256": source_problem_sha256,
        "source_problem_path": source_problem_path,
        "source_run": source_run,
        "source_model": source_model,
    }
    return {"id": _record_id(body), **body}


def permitted_assumptions(problem: str) -> list[str]:
    """Extract a Markdown section when present; never infer missing assumptions."""
    match = re.search(r"(?im)^##\s+permitted assumptions\s*$", problem)
    if not match:
        return ["Assumptions were not separately specified; inspect the full source problem."]
    rest = problem[match.end():]
    next_section = re.search(r"(?m)^##\s+", rest)
    text = rest[:next_section.start() if next_section else None].strip()
    return [text] if text else ["Permitted assumptions section was empty."]


def _terms(text: str) -> set[str]:
    return {word for word in re.findall(r"(?u)\w+", text.casefold()) if len(word) >= 3 and word not in STOPWORDS}


class SharedLibrary:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.records_dir = self.directory / "records"
        self.disputes_dir = self.directory / "disputes"

    def publish(self, record: dict[str, Any]) -> Path:
        body = {key: value for key, value in record.items() if key != "id"}
        if record.get("id") != _record_id(body):
            raise ValueError("library record digest does not match content")
        if len(_canonical(record).encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("library record exceeds the size limit")
        self.records_dir.mkdir(parents=True, exist_ok=True)
        target = self.records_dir / f"{record['id']}.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing != record:
                raise ValueError(f"existing library record was changed: {target}")
            return target
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.records_dir, prefix=".record-", delete=False) as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, target)
        return target

    def dispute(self, record_id: str, evidence: str) -> Path:
        """Keep the immutable record, but exclude this version from future imports."""
        if len(record_id) != 64 or any(c not in "0123456789abcdef" for c in record_id):
            raise ValueError("invalid disputed record ID")
        if not (self.records_dir / f"{record_id}.json").is_file():
            raise ValueError("cannot dispute an unpublished record")
        self.disputes_dir.mkdir(parents=True, exist_ok=True)
        target = self.disputes_dir / f"{record_id}.json"
        if not target.exists():
            content = json.dumps({"record_id": record_id, "evidence": evidence}, ensure_ascii=False, indent=2) + "\n"
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.disputes_dir, prefix=".dispute-", delete=False) as handle:
                handle.write(content)
                temporary = Path(handle.name)
            os.replace(temporary, target)
        return target

    def load(self) -> tuple[list[dict[str, Any]], int]:
        if not self.records_dir.exists():
            return [], 0
        records: list[dict[str, Any]] = []
        rejected = 0
        for path in sorted(self.records_dir.glob("*.json")):
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("not a regular record file")
                if path.stat().st_size > MAX_RECORD_BYTES:
                    raise ValueError("record too large")
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or record.get("schema_version") != 1:
                    raise ValueError("invalid schema")
                body = {key: value for key, value in record.items() if key != "id"}
                if record.get("id") != path.stem or record["id"] != _record_id(body):
                    raise ValueError("invalid digest")
                if record.get("status") not in {"unverified", "model_checked"} or record.get("kind") not in {"claim", "solution"}:
                    raise ValueError("invalid status or kind")
                if not isinstance(record.get("statement"), str) or not isinstance(record.get("argument"), str):
                    raise ValueError("invalid mathematical text")
                if not isinstance(record.get("source_problem_path"), str) or not isinstance(record.get("source_problem_sha256"), str):
                    raise ValueError("invalid provenance")
                if not isinstance(record.get("assumptions"), list) or not all(isinstance(x, str) for x in record["assumptions"]):
                    raise ValueError("invalid assumptions")
                if not isinstance(record.get("dependencies"), list):
                    raise ValueError("invalid dependencies")
                records.append(record)
            except (OSError, ValueError, KeyError, TypeError):
                rejected += 1
        return records, rejected

    def retrieve(self, problem: str, problem_sha256: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        records, rejected = self.load()
        if limit == 0:
            return [], rejected
        query = _terms(problem)
        ranked = []
        for record in records:
            if record.get("source_problem_sha256") == problem_sha256:
                continue
            if (self.disputes_dir / f"{record['id']}.json").is_file():
                continue
            searchable = " ".join([record["statement"], *record["assumptions"]])
            overlap = len(query & _terms(searchable))
            if overlap:
                ranked.append((overlap, record["status"] == "model_checked", record["id"], record))
        ranked.sort(key=lambda item: (-item[0], -int(item[1]), item[2]))
        selected: list[dict[str, Any]] = []
        used = 0
        for _, _, _, record in ranked:
            size = len(_canonical(record))
            if used + size <= MAX_IMPORT_CHARS:
                selected.append(record)
                used += size
            if len(selected) >= limit:
                break
        return selected, rejected
