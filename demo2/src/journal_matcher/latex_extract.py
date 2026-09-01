"""Small, deliberately conservative LaTeX structure extractor.

The extractor does not try to compile or understand mathematical macros.  It
only preserves the text needed by the classifier and gives every theorem-like
environment a stable identifier.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from .schemas import ExtractedManuscript, TheoremRecord


_DEFAULT_THEOREM_ENVS = {
    "theorem",
    "lemma",
    "proposition",
    "corollary",
    "claim",
    "conjecture",
    "result",
    "question",
    "definition",
    "construction",
}


def _strip_comments(text: str) -> str:
    """Remove TeX comments while preserving escaped percent signs."""

    return re.sub(r"(?<!\\)%[^\n]*", "", text)


def _balanced_argument(text: str, opening: int) -> Tuple[str, int]:
    """Return a braced argument and the index immediately after it."""

    if opening >= len(text) or text[opening] != "{":
        return "", opening
    depth = 0
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[opening + 1 : index], index + 1
    return text[opening + 1 :], len(text)


def _command_argument(text: str, command: str) -> str:
    match = re.search(r"\\" + re.escape(command) + r"\s*(?:\[[^\]]*\])?\s*\{", text)
    if not match:
        return ""
    value, _ = _balanced_argument(text, text.find("{", match.start()))
    return value.strip()


def _environment_body(text: str, name: str, start: int = 0) -> Optional[Tuple[str, int, int]]:
    begin = re.compile(r"\\begin\s*\{\s*" + re.escape(name) + r"\s*\}", re.I)
    end = re.compile(r"\\end\s*\{\s*" + re.escape(name) + r"\s*\}", re.I)
    opening = begin.search(text, start)
    if not opening:
        return None
    cursor = opening.end()
    depth = 1
    while depth:
        next_begin = begin.search(text, cursor)
        next_end = end.search(text, cursor)
        if not next_end:
            return text[cursor:], cursor, len(text)
        if next_begin and next_begin.start() < next_end.start():
            depth += 1
            cursor = next_begin.end()
        else:
            depth -= 1
            if depth == 0:
                return text[cursor : next_end.start()], cursor, next_end.start()
            cursor = next_end.end()
    return None


def _theorem_environments(text: str) -> List[str]:
    environments = set(_DEFAULT_THEOREM_ENVS)
    for match in re.finditer(r"\\newtheorem\s*\{\s*([^}]+)\s*\}", text):
        environments.add(match.group(1).strip())
    return sorted(environments)


def _sections(text: str) -> List[Tuple[str, int, int]]:
    pattern = re.compile(r"\\(?:part|chapter|section|subsection|subsubsection)\*?\s*\{", re.I)
    found: List[Tuple[str, int, int]] = []
    for match in pattern.finditer(text):
        title, end = _balanced_argument(text, text.find("{", match.start()))
        found.append((re.sub(r"\s+", " ", title).strip(), match.start(), end))
    return found


def _section_text(text: str, sections: Sequence[Tuple[str, int, int]], names: Iterable[str]) -> str:
    wanted = tuple(name.lower() for name in names)
    for index, (title, start, content_start) in enumerate(sections):
        if any(name in title.lower() for name in wanted):
            end = sections[index + 1][1] if index + 1 < len(sections) else len(text)
            return text[content_start:end].strip()
    return ""


def _clean_statement(value: str) -> str:
    value = re.sub(r"\\label\s*\{[^}]*\}", "", value)
    value = re.sub(r"\\(?:begin|end)\s*\{[^}]*\}", "", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _extract_theorems(text: str, sections: Sequence[Tuple[str, int, int]]) -> List[TheoremRecord]:
    results: List[TheoremRecord] = []
    ordinal = 0
    for environment in _theorem_environments(text):
        cursor = 0
        while True:
            found = _environment_body(text, environment, cursor)
            if found is None:
                break
            body, content_start, content_end = found
            ordinal += 1
            label_match = re.search(r"\\label\s*\{([^}]+)\}", body)
            label = label_match.group(1).strip() if label_match else None
            section = None
            for title, start, _ in sections:
                if start <= content_start:
                    section = title
                else:
                    break
            result_id = label or "%s-%d" % (environment, ordinal)
            results.append(
                TheoremRecord(
                    result_id=result_id,
                    environment=environment,
                    statement=_clean_statement(body),
                    label=label,
                    section=section,
                )
            )
            cursor = max(content_end, cursor + 1)
    results.sort(key=lambda item: text.find(item.label and "\\label{" + item.label + "}" or item.statement))
    return results


def _bibliography(text: str) -> List[dict]:
    entries: List[dict] = []
    for match in re.finditer(r"\\bibitem(?:\[[^\]]*\])?\s*\{([^}]+)\}(.*?)(?=\\bibitem|\\end\s*\{thebibliography\}|$)", text, re.S):
        body = re.sub(r"\s+", " ", match.group(2)).strip()
        doi = re.search(r"10\.\d{4,9}/[^\s}]+", body, re.I)
        entries.append({"key": match.group(1).strip(), "text": body, "doi": doi.group(0) if doi else ""})
    for match in re.finditer(r"@([A-Za-z]+)\s*\{\s*([^,]+),(.*?)(?=\n\s*@|\Z)", text, re.S):
        body = re.sub(r"\s+", " ", match.group(3)).strip()
        doi = re.search(r"doi\s*=\s*[\{\"]([^}\"]+)", body, re.I)
        entries.append({"key": match.group(2).strip(), "text": body, "doi": doi.group(1).strip() if doi else ""})
    return entries


def extract_text(text: str, source_path: str = "<string>") -> ExtractedManuscript:
    text = _strip_comments(text)
    section_records = _sections(text)
    sections = [title for title, _, _ in section_records]
    abstract = ""
    abstract_body = _environment_body(text, "abstract")
    if abstract_body:
        abstract = abstract_body[0].strip()
    introduction = _section_text(text, section_records, ("introduction", "background"))
    conclusion = _section_text(text, section_records, ("conclusion", "discussion", "summary"))
    if not introduction:
        if abstract_body:
            first_content = text[abstract_body[2] :]
        elif section_records:
            first_content = text[section_records[0][2] :]
        else:
            first_content = text
        introduction = first_content[:12000].strip()
    return ExtractedManuscript(
        source_path=source_path,
        title=_command_argument(text, "title"),
        abstract=abstract,
        introduction=introduction,
        sections=sections,
        theorems=_extract_theorems(text, section_records),
        conclusion=conclusion,
        bibliography=_bibliography(text),
    )


def extract_manuscript(path: Union[str, Path]) -> ExtractedManuscript:
    manuscript_path = Path(path)
    if manuscript_path.suffix.lower() not in {".tex", ".latex"}:
        raise ValueError("expected a .tex or .latex manuscript")
    return extract_text(manuscript_path.read_text(encoding="utf-8"), str(manuscript_path))
