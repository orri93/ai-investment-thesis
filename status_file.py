"""Helpers for the leverage block embedded in thesis status files.

`main.py` regenerates status files from SEC evaluations and `leverage-evaluator.py`
injects a leverage block into them, so both must agree on how that block is found,
removed and re-inserted.
"""

from __future__ import annotations

LEVERAGE_STATUS_START_MARKER = "<!-- leverage-status-start -->"
LEVERAGE_STATUS_END_MARKER = "<!-- leverage-status-end -->"
LATEST_ASSESSMENT_HEADER = "## latest assessment"


def extract_leverage_block(status_text: str) -> list[str] | None:
    """Return the lines of the first complete leverage block, markers included."""
    lines = status_text.splitlines()
    span = _find_block(lines)
    if span is None:
        return None
    start, end = span
    return lines[start : end + 1]


def remove_leverage_blocks(status_text: str) -> str:
    """Return status_text with every complete leverage block removed."""
    lines = status_text.splitlines()
    while (span := _find_block(lines)) is not None:
        start, end = span
        lines = lines[:start] + lines[end + 1 :]
    result = "\n".join(lines)
    return result + "\n" if status_text.endswith("\n") else result


def insert_leverage_block(status_text: str, block_lines: list[str]) -> str | None:
    """Place block_lines at the end of the "Latest assessment" section.

    Any existing leverage block is replaced. Returns None when the status file has
    no "Latest assessment" section.
    """
    lines = remove_leverage_blocks(status_text).splitlines()

    latest_idx = next(
        (i for i, line in enumerate(lines) if line.strip().lower() == LATEST_ASSESSMENT_HEADER),
        -1,
    )
    if latest_idx == -1:
        return None

    section_end = next(
        (i for i in range(latest_idx + 1, len(lines)) if lines[i].strip().startswith("## ")),
        len(lines),
    )

    section = lines[latest_idx + 1 : section_end]
    while section and not section[-1].strip():
        section.pop()
    new_section = section + [""] + list(block_lines)
    if section_end < len(lines):
        new_section.append("")

    new_lines = lines[: latest_idx + 1] + new_section + lines[section_end:]
    return "\n".join(new_lines).rstrip() + "\n"


def _find_block(lines: list[str]) -> tuple[int, int] | None:
    start = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == LEVERAGE_STATUS_START_MARKER:
            start = i
        elif stripped == LEVERAGE_STATUS_END_MARKER and start != -1:
            return start, i
    return None
