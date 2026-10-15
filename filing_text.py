"""Convert SEC filing HTML into plain text and build budget-aware excerpts.

Raw truncation of a 10-K/10-Q mostly yields the cover page, the hidden inline-XBRL
header and risk factors, while MD&A and the financial statements are cut off.
These helpers strip the noise and select the decision-relevant sections instead.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ExhibitText:
    document_type: str
    description: str
    raw_text: str


_BLOCK_TAG_RE = re.compile(
    r"(?i)</?(?:br|p|div|tr|li|ul|ol|h[1-6]|table|thead|tbody|tfoot|section|article|center)\b[^>]*>"
)
_CELL_TAG_RE = re.compile(r"(?i)<(?:td|th)\b[^>]*>")
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_SEPARATOR_RUN_RE = re.compile(r"(?:\s*\|\s*)+")
# Repeated page headers/footers that only consume budget.
_PAGE_NOISE_RE = re.compile(r"^(?:table of contents|page \d{1,3}|\d{1,3})$", re.IGNORECASE)
_STATEMENT_TITLE_RE = re.compile(
    r"^consolidated (?:statements? of|balance sheets?)|^condensed consolidated (?:statements? of|balance sheets?)",
    re.IGNORECASE,
)

_ITEM_HEADING_RE = re.compile(
    r"^(?:part\s+i{1,3}v?\s*[|,.:\-\u2013\u2014]*\s*)?item\s*(\d{1,2}[a-c]?)\b\s*[.:\-\u2013\u2014|]?",
    re.IGNORECASE,
)
_MAX_HEADING_LEN = 160

# Section keys in priority order with their share of the character budget.
_PERIODIC_SECTIONS: tuple[tuple[str, str, float], ...] = (
    ("mdna", "Management's Discussion and Analysis", 0.40),
    ("financials", "Financial Statements", 0.33),
    ("risk", "Risk Factors", 0.15),
    ("market_risk", "Quantitative and Qualitative Disclosures About Market Risk", 0.05),
)
_INTRO_SHARE = 0.04
_INTRO_MAX_CHARS = 3000


def html_to_text(raw: str) -> str:
    """Return line-preserving plain text from filing HTML (or pass plain text through)."""
    text = re.sub(r"(?is)<ix:header\b.*?</ix:header>", " ", raw)
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1\s*>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _CELL_TAG_RE.sub(" | ", text)
    text = _ANY_TAG_RE.sub(" ", text)
    text = html.unescape(text)

    lines: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line)
        line = _SEPARATOR_RUN_RE.sub(" | ", line)
        # Re-attach currency symbols, parentheses and percent signs split across cells.
        line = re.sub(r"\$ \| ", "$", line)
        line = re.sub(r" \| ([)%])", r"\1", line)
        line = re.sub(r"\(\s+(?=[\d$])", "(", line)
        line = re.sub(r"(?<=\d)\s+\)", ")", line)
        line = line.strip(" |")
        if line and not _PAGE_NOISE_RE.match(line):
            lines.append(line)
    return "\n".join(lines)


def build_filing_excerpt(
    form: str,
    primary_raw: str,
    exhibits: Sequence[ExhibitText] = (),
    *,
    max_chars: int,
) -> str:
    """Build the filing excerpt sent to the model for the given form type."""
    primary_text = html_to_text(primary_raw)
    base_form = form.upper().split("/")[0]

    if base_form in ("10-K", "10-Q"):
        return select_periodic_sections(primary_text, base_form, max_chars=max_chars)

    if exhibits:
        segments = [(f"[{form} primary document]", primary_text, 0.2)]
        exhibit_share = 0.8 / len(exhibits)
        for exhibit in exhibits:
            label = f"[Exhibit {exhibit.document_type}"
            if exhibit.description and exhibit.description != exhibit.document_type:
                label += f": {exhibit.description}"
            label += "]"
            segments.append((label, html_to_text(exhibit.raw_text), exhibit_share))
        return _allocate(segments, max_chars)

    return _truncate(primary_text, max_chars)


def select_periodic_sections(text: str, form: str, *, max_chars: int) -> str:
    """Select MD&A, financial statements and risk sections from 10-K/10-Q text."""
    if len(text) <= max_chars:
        return text

    lines = text.splitlines()
    sections = _locate_sections(lines, form)
    if "mdna" not in sections and "financials" not in sections:
        return _truncate(text, max_chars)

    intro_end = min(sections.values(), key=lambda bounds: bounds[0])[0]
    intro = "\n".join(lines[:intro_end])
    intro_budget = min(_INTRO_MAX_CHARS, int(max_chars * _INTRO_SHARE))

    segments: list[tuple[str, str, float]] = [
        ("[Cover page / introduction]", intro[:intro_budget], _INTRO_SHARE),
    ]
    for key, title, share in _PERIODIC_SECTIONS:
        if key in sections:
            start, end = sections[key]
            section_lines = lines[start:end]
            if key == "financials":
                section_lines = _skip_to_first_statement(section_lines)
            segments.append((f"[{title}]", "\n".join(section_lines), share))
    return _allocate(segments, max_chars)


def _skip_to_first_statement(section_lines: list[str]) -> list[str]:
    """Drop the statement index and auditor report that precede the first statement table."""
    for idx, line in enumerate(section_lines[1:], start=1):
        if not _STATEMENT_TITLE_RE.match(line):
            continue
        # A real statement is followed by table rows; index entries are not.
        if any(" | " in following for following in section_lines[idx + 1 : idx + 8]):
            return section_lines[:1] + section_lines[idx:]
    return section_lines


def _locate_sections(lines: list[str], form: str) -> dict[str, tuple[int, int]]:
    headings: list[tuple[int, str | None]] = []
    for idx, line in enumerate(lines):
        if len(line) > _MAX_HEADING_LEN:
            continue
        match = _ITEM_HEADING_RE.match(line)
        if not match:
            continue
        heading = line
        if idx + 1 < len(lines) and len(lines[idx + 1]) <= _MAX_HEADING_LEN:
            # Titles are sometimes split from the "Item N." label onto the next line.
            heading = f"{line} {lines[idx + 1]}"
        headings.append((idx, _classify_heading(match.group(1).lower(), heading, form)))

    # Tables of contents repeat every heading, so keep the occurrence that starts
    # the longest section for each key.
    best: dict[str, tuple[int, int]] = {}
    for position, (start, key) in enumerate(headings):
        if key is None:
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        length = sum(len(line) for line in lines[start:end])
        current = best.get(key)
        if current is None or length > sum(len(line) for line in lines[current[0] : current[1]]):
            best[key] = (start, end)
    return best


def _classify_heading(item: str, heading: str, form: str) -> str | None:
    lowered = heading.lower().replace("\u2019", "'")
    if "discussion and analysis" in lowered:
        return "mdna"
    if "quantitative and qualitative" in lowered:
        return "market_risk"
    if "risk factors" in lowered and item == "1a":
        return "risk"
    if "financial statements" in lowered and (
        (form == "10-K" and item == "8") or (form == "10-Q" and item == "1")
    ):
        return "financials"
    return None


def _allocate(segments: list[tuple[str, str, float]], max_chars: int) -> str:
    """Fit labelled segments into max_chars, redistributing unused share in order."""
    # Reserve room for labels, separators and truncation markers.
    label_overhead = sum(len(label) + 30 for label, _, _ in segments)
    budget = max(0, max_chars - label_overhead)
    total_share = sum(share for _, _, share in segments) or 1.0

    allotted = [min(len(text), int(budget * share / total_share)) for _, text, share in segments]
    remaining = budget - sum(allotted)
    for index, (_, text, _) in enumerate(segments):
        if remaining <= 0:
            break
        extra = min(remaining, len(text) - allotted[index])
        allotted[index] += extra
        remaining -= extra

    parts: list[str] = []
    for (label, text, _), limit in zip(segments, allotted):
        if not text.strip() or limit <= 0:
            continue
        body = text if len(text) <= limit else text[:limit].rstrip() + "\n[... truncated ...]"
        parts.append(f"{label}\n{body}")
    return _truncate("\n\n".join(parts), max_chars)


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars]
