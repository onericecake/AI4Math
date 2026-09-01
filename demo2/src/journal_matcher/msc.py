"""MSC2020 taxonomy helpers.

The taxonomy is data, not code.  A complete MSC2020 JSON file can be imported
with :class:`MSCTaxonomy`; the small built-in entries merely make the CLI's
error messages useful when the data file has not yet been installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union


@dataclass(frozen=True)
class MSCEntry:
    code: str
    name: str
    parent: Optional[str] = None
    description: str = ""


class MSCTaxonomy:
    def __init__(self, entries: Iterable[MSCEntry] = ()) -> None:
        self.entries: Dict[str, MSCEntry] = {entry.code: entry for entry in entries}

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "MSCTaxonomy":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, Mapping):
            raw_entries = raw.get("codes", raw.get("entries", raw))
        else:
            raw_entries = raw
        entries: List[MSCEntry] = []
        def add_item(item: Mapping[str, Any], parent: Optional[str] = None) -> None:
            if "code" not in item:
                return
            code = normalize_msc_code(str(item["code"]))
            declared_parent = item.get("parent")
            entry_parent = normalize_msc_code(str(declared_parent)) if declared_parent else parent
            entries.append(
                MSCEntry(
                    code=code,
                    name=str(item.get("name", item.get("description", ""))),
                    parent=entry_parent,
                    description=str(item.get("description", "")),
                )
            )
            for child in item.get("children", []) if isinstance(item.get("children", []), list) else []:
                if isinstance(child, Mapping):
                    add_item(child, code)

        if isinstance(raw_entries, Mapping):
            raw_entries = [dict(value, code=key) if isinstance(value, Mapping) else {"code": key, "name": str(value)} for key, value in raw_entries.items()]
        for item in raw_entries:
            if isinstance(item, Mapping):
                add_item(item)
        return cls(entries)

    def add(self, entry: MSCEntry) -> None:
        self.entries[entry.code] = entry

    def get(self, code: str) -> Optional[MSCEntry]:
        return self.entries.get(normalize_msc_code(code))

    def children(self, code: str) -> List[MSCEntry]:
        normalized = normalize_msc_code(code)
        return sorted((item for item in self.entries.values() if item.parent == normalized), key=lambda item: item.code)

    def two_digit(self) -> List[MSCEntry]:
        return sorted((item for item in self.entries.values() if re.fullmatch(r"\d{2}", item.code)), key=lambda item: item.code)

    def descendants(self, code: str) -> List[MSCEntry]:
        normalized = normalize_msc_code(code)
        return sorted((item for item in self.entries.values() if item.code.startswith(normalized) and item.code != normalized), key=lambda item: item.code)

    def prompt_context(self, codes: Optional[Iterable[str]] = None) -> str:
        selected_codes = self.entries.keys() if codes is None else codes
        selected = [self.entries[normalize_msc_code(code)] for code in selected_codes if normalize_msc_code(code) in self.entries]
        return "\n".join("%s — %s" % (item.code, item.name or item.description) for item in selected)

    def is_complete(self) -> bool:
        return len(self.two_digit()) >= 40


def normalize_msc_code(code: str) -> str:
    value = code.strip().upper().replace(" ", "")
    if "-" in value:
        match = re.fullmatch(r"(\d{2})-([0-9A-Z]{2})", value)
        if not match:
            raise ValueError("invalid MSC code: %s" % code)
        return value if match.group(2) != "XX" else match.group(1)
    if value.endswith("XX"):
        value = value[:-2]
    if not re.fullmatch(r"\d{2}[A-Z]{0,2}\d{0,2}", value):
        raise ValueError("invalid MSC code: %s" % code)
    return value


def default_taxonomy() -> MSCTaxonomy:
    """Return a tiny fallback taxonomy; production runs should load MSC2020."""

    return MSCTaxonomy(
        [
            MSCEntry("00", "General and overarching topics"),
            MSCEntry("01", "History and biography"),
            MSCEntry("03", "Mathematical logic and foundations"),
            MSCEntry("05", "Combinatorics", description="Combinatorics"),
            MSCEntry("11", "Number theory"),
            MSCEntry("14", "Algebraic geometry"),
            MSCEntry("35", "Partial differential equations"),
            MSCEntry("46", "Functional analysis"),
            MSCEntry("60", "Probability theory and stochastic processes"),
            MSCEntry("68", "Computer science", description="Computer science"),
            MSCEntry("76", "Fluid mechanics"),
            MSCEntry("90", "Operations research, mathematical programming"),
        ]
    )
