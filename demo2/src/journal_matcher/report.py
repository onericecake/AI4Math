from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from .schemas import MatchReport


def render_markdown(report: MatchReport) -> str:
    profile = report.profile
    broad = ", ".join("%s %s" % (item.code, item.name) for item in profile.broad_fields) or "Unknown"
    primary = "%s %s" % (profile.primary_msc.code, profile.primary_msc.name) if profile.primary_msc else "Unknown"
    secondary = ", ".join("%s %s" % (item.code, item.name) for item in profile.secondary_msc) or "None recorded"
    lines = [
        "# Mathematics journal matching report",
        "",
        "## Central result",
        "",
        report.central_result_text or "The central result was not supplied.",
        "",
        "## Mathematical classification",
        "",
        "Broad fields: " + broad,
        "Primary MSC: " + primary,
        "Secondary MSC: " + secondary,
        "Methods: " + (", ".join(profile.methods) or "Unknown"),
        "",
        "## Contribution profile",
        "",
        "Contribution: " + profile.contribution_type,
        "Technical depth: " + profile.technical_depth,
        "Audience: " + profile.audience,
        "Audience breadth: " + profile.audience_breadth,
        "Conceptual character: " + profile.conceptual_character,
        "",
        "## Recommendations",
        "",
    ]
    if not report.recommendations:
        lines.append("No recommendation was supported by the available catalog evidence.")
    for index, item in enumerate(report.recommendations, 1):
        lines.extend(
            [
                "%d. %s — %s" % (index, item.journal_name, item.fit),
                "",
                "Role: " + item.role,
                "Level fit: " + item.level_fit,
                "Why: " + (" ".join(item.reasons) or "No reasons returned."),
                "Important mismatch: " + (item.important_mismatch or "None recorded."),
                "Submission emphasis: " + (item.submission_emphasis or "None recorded."),
                "Representative articles: " + (", ".join(item.representative_article_ids) or "None recorded."),
                "",
            ]
        )
    if report.catalog_limitations:
        lines.extend(["## Limitations", ""])
        lines.extend("- " + item for item in report.catalog_limitations)
        lines.append("")
    lines.extend(
        [
            "The system describes subject and field-relative fit. It does not assess proof correctness or predict acceptance.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: MatchReport, markdown_path: Union[str, Path], json_path: Union[str, Path]) -> None:
    Path(markdown_path).write_text(render_markdown(report), encoding="utf-8")
    Path(json_path).write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
