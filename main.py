from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from filing_text import ExhibitText
from openai_evaluator import EvaluationInput, OpenAIEvaluatorError, OpenAIThesisEvaluator
from sec_filings import SUPPORTED_FORMS, FilingRecord, SecEdgarError, SecFilingsClient
from status_file import extract_leverage_block, insert_leverage_block, remove_leverage_blocks
from utils import (
    first_content_line,
    load_environment,
    report_unexpected_error,
    ticker_from_thesis_path,
    write_text_atomic,
)


ROOT_DIR = Path(__file__).resolve().parent
THESIS_DIR = ROOT_DIR / "thesis"
INSTRUCTIONS_DIR = ROOT_DIR / "instructions"
LOG_DIR = ROOT_DIR / "log"
STATUS_DIR = ROOT_DIR / "status"
STATUS_INSTRUCTION_FILE = "status.md"

FORM_INSTRUCTION_FILES = {
    "10-K": "10-k.md",
    "10-Q": "10-q.md",
    "8-K": "8-k.md",
}

PROCESSED_MARKER_TEMPLATE = "<!-- processed-sec-filing:{accession} -->"
PROCESSED_MARKER_PREFIX = "<!-- processed-sec-filing:"
EVALUATION_LOG_HEADER = "## Evaluation Log"
STATUS_SOURCE_MARKER_TEMPLATE = "<!-- status-source-accession:{accession} -->"
STATUS_SOURCE_MARKER_RE = re.compile(r"^\s*<!--\s*status-source-accession:.*?-->\s*$", re.MULTILINE)
UPDATED_ON_RE = re.compile(r"^(\s*[-*]\s*Updated on:).*$", re.MULTILINE | re.IGNORECASE)
VERDICT_LINE_RE = re.compile(r"^\s*[-*]\s*Verdict:", re.MULTILINE | re.IGNORECASE)
ALLOWED_VERDICTS = ("No Action", "Add", "Hold", "Trim", "Exit", "Watch", "Reduce", "Maintain")
VERDICT_STATUS_COLORS = {
    "Add": "Green",
    "Hold": "Green",
    "Maintain": "Green",
    "No Action": "Green",
    "Watch": "Yellow",
    "Trim": "Yellow",
    "Reduce": "Yellow",
    "Exit": "Red",
}
# 8-K cover pages rarely contain the news itself; it lives in exhibits such as EX-99.1.
EXHIBIT_FORMS = ("8-K",)
EXHIBIT_TYPE_PREFIXES = ("EX-99",)
MAX_EXHIBITS_PER_FILING = 3

PERIODIC_FORMS = ("10-K", "10-Q")
LOG_ENTRY_HEADER_RE = re.compile(
    r"^### (SEC Filing Review|Thesis Revision Review):\s*(10-K|10-Q|8-K)\s*"
    r"\((\d{4}-\d{2}-\d{2})\)\s*-\s*([0-9-]+)\s*$",
    re.MULTILINE,
)
PROCESSED_ON_RE = re.compile(r"^- Processed on:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
THESIS_FINGERPRINT_TEMPLATE = "<!-- thesis-sha256:{fingerprint} -->"
THESIS_FINGERPRINT_RE = re.compile(r"<!-- thesis-sha256:([0-9a-f]{64}) -->")
REVISION_MARKER_TEMPLATE = "<!-- thesis-revision-review:{fingerprint}:{accession} -->"
REVISION_FINGERPRINT_RE = re.compile(r"<!-- thesis-revision-review:([0-9a-f]+):")
REVISION_REVIEW_NOTE = (
    "The investor revised the thesis after this filing was last reviewed. Re-evaluate the "
    "revised thesis against this filing: state which changes the filing supports or "
    "contradicts, and whether the verdict changes."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Process thesis files against new SEC 10-K/10-Q/8-K filings and append "
            "OpenAI-generated decision log entries."
        )
    )
    parser.add_argument(
        "--thesis-dir",
        default=str(THESIS_DIR),
        help=f"Path to thesis markdown files. Default: {THESIS_DIR}",
    )
    parser.add_argument(
        "--instructions-dir",
        default=str(INSTRUCTIONS_DIR),
        help=f"Path to form instruction markdown files. Default: {INSTRUCTIONS_DIR}",
    )
    parser.add_argument(
        "--filings-limit",
        type=int,
        default=25,
        help=(
            "Minimum number of recent SEC filings to scan per thesis ticker. On later runs the "
            "scan continues past this limit until it reaches a filing already in the log, so a "
            "backlog is never skipped. Filings before the thesis purchase date are always "
            "excluded. Default: 25"
        ),
    )
    parser.add_argument(
        "--openai-model",
        default=None,
        help="Optional override for OPENAI_MODEL.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(LOG_DIR),
        help=f"Path to decision log markdown files. Default: {LOG_DIR}",
    )
    parser.add_argument(
        "--status-dir",
        default=str(STATUS_DIR),
        help=f"Path to thesis status markdown files. Default: {STATUS_DIR}",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full tracebacks for unexpected errors.",
    )
    return parser


def main() -> int:
    load_environment()
    args = build_parser().parse_args()
    thesis_dir = Path(args.thesis_dir)
    instructions_dir = Path(args.instructions_dir)
    log_dir = Path(args.log_dir)
    status_dir = Path(args.status_dir)

    try:
        instruction_texts = _load_instruction_texts(instructions_dir)
        status_instruction_text = _load_status_instruction_text(instructions_dir)
        sec_client = SecFilingsClient()
        evaluator = OpenAIThesisEvaluator(model=args.openai_model)
    except (SecEdgarError, OpenAIEvaluatorError, FileNotFoundError, ValueError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
        return 1

    thesis_files = sorted(thesis_dir.glob("*.md"))
    if not thesis_files:
        print(f"No thesis files found in: {thesis_dir}")
        return 0

    print("SEC thesis revalidation run started")
    print(f"- Thesis files: {len(thesis_files)}")
    print(f"- Log directory: {log_dir}")
    print(f"- Status directory: {status_dir}")
    print(f"- Forms: {', '.join(SUPPORTED_FORMS)}")
    print()

    log_dir.mkdir(parents=True, exist_ok=True)
    status_dir.mkdir(parents=True, exist_ok=True)

    processed_count = 0
    revision_count = 0
    skipped_count = 0
    failed_count = 0

    for thesis_path in thesis_files:
        print(f"Working on thesis: {thesis_path.name}")
        try:
            thesis_text = thesis_path.read_text(encoding="utf-8")
            ticker = ticker_from_thesis_path(thesis_path)
            log_path = log_dir / thesis_path.name
            log_text = _load_or_initialize_log(log_path, ticker)

            purchase_date = _parse_purchase_date(thesis_text)
            if purchase_date:
                print(f"- Position purchase date: {purchase_date} (filtering earlier filings)")

            filings = _collect_filings_to_scan(
                sec_client,
                ticker,
                log_text=log_text,
                purchase_date=purchase_date,
                filings_limit=args.filings_limit,
            )
            print(f"- SEC filings scanned: {len(filings)}")
            if len(filings) > args.filings_limit:
                print("  (scan extended past --filings-limit to catch up with the log)")

            new_filings = [
                filing
                for filing in filings
                if not _already_processed(log_text, filing.accession_number)
            ]
            new_filings.sort(
                key=lambda filing: (
                    filing.filing_date,
                    filing.acceptance_datetime or "",
                    filing.accession_number,
                )
            )
            if not new_filings:
                print("- No new filings to process")
                skipped_count += 1
            else:
                print(f"- New filings available: {len(new_filings)}")

            periodic_reviewed = False
            for filing in new_filings:
                print(
                    f"  - Evaluating {filing.form} filed {filing.filing_date} "
                    f"({filing.accession_number})"
                )

                instruction_text = instruction_texts.get(filing.form)
                if not instruction_text:
                    print(f"    Skipped: no instruction file configured for {filing.form}")
                    continue

                filing_doc = sec_client.fetch_document(filing)
                exhibits = _fetch_exhibit_texts(sec_client, filing)

                evaluation = evaluator.evaluate(
                    EvaluationInput(
                        ticker=ticker,
                        form=filing.form,
                        filing_date=filing.filing_date,
                        accession_number=filing.accession_number,
                        filing_url=filing.primary_document_url,
                        instruction_text=instruction_text,
                        thesis_text=thesis_text,
                        filing_text=filing_doc.text,
                        exhibits=exhibits,
                    )
                )

                log_text = _append_evaluation_log_entry(log_text, filing, evaluation)
                write_text_atomic(log_path, log_text)

                print("    Result summary:")
                print(f"    {first_content_line(evaluation)}")
                processed_count += 1
                periodic_reviewed = periodic_reviewed or filing.form in PERIODIC_FORMS

            log_text, revised = _review_thesis_change(
                ticker=ticker,
                thesis_text=thesis_text,
                log_text=log_text,
                log_path=log_path,
                sec_client=sec_client,
                evaluator=evaluator,
                instruction_texts=instruction_texts,
                periodic_reviewed_this_run=periodic_reviewed,
            )
            revision_count += int(revised)

            # Always sync: the status may be stale if an earlier run failed after logging.
            status_path = status_dir / thesis_path.name
            status_updated = _update_status_file_if_needed(
                ticker=ticker,
                log_text=log_text,
                status_path=status_path,
                evaluator=evaluator,
                status_instruction_text=status_instruction_text,
            )
            if status_updated:
                print(f"- Status updated: {status_path.name}")
            else:
                print("- Status unchanged (already reflects latest relevant filing)")

            print()
        except (SecEdgarError, OpenAIEvaluatorError, ValueError, FileNotFoundError) as exc:
            print(f"- Failed: {exc}", file=sys.stderr)
            print()
            failed_count += 1
        except Exception as exc:
            report_unexpected_error(exc, verbose=args.verbose)
            print()
            failed_count += 1

    print("Run complete")
    print(f"- Filings processed: {processed_count}")
    print(f"- Thesis revision reviews: {revision_count}")
    print(f"- Theses with no new filings: {skipped_count}")
    print(f"- Theses failed: {failed_count}")
    return 0 if failed_count == 0 else 1


def _load_instruction_texts(instructions_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for form, file_name in FORM_INSTRUCTION_FILES.items():
        file_path = instructions_dir / file_name
        if not file_path.exists():
            raise FileNotFoundError(f"Missing instruction file: {file_path}")
        result[form] = file_path.read_text(encoding="utf-8").strip()
    return result


def _load_status_instruction_text(instructions_dir: Path) -> str:
    path = instructions_dir / STATUS_INSTRUCTION_FILE
    if not path.exists():
        raise FileNotFoundError(f"Missing status instruction file: {path}")
    return path.read_text(encoding="utf-8").strip()


def _fetch_exhibit_texts(
    sec_client: SecFilingsClient,
    filing: FilingRecord,
) -> tuple[ExhibitText, ...]:
    if filing.form not in EXHIBIT_FORMS:
        return ()
    try:
        exhibits = sec_client.fetch_exhibits(
            filing,
            type_prefixes=EXHIBIT_TYPE_PREFIXES,
            limit=MAX_EXHIBITS_PER_FILING,
        )
    except SecEdgarError as exc:
        print(f"    Warning: could not fetch exhibits, using primary document only ({exc})")
        return ()

    if exhibits:
        types = ", ".join(exhibit.attachment.document_type for exhibit in exhibits)
        print(f"    Exhibits included: {types}")
    return tuple(
        ExhibitText(
            document_type=exhibit.attachment.document_type,
            description=exhibit.attachment.description,
            raw_text=exhibit.text,
        )
        for exhibit in exhibits
    )


def _load_or_initialize_log(log_path: Path, ticker: str) -> str:
    if log_path.exists():
        return log_path.read_text(encoding="utf-8")

    # Initialize a new log from the ticker/file name, not thesis markdown headers.
    log_text = f"# {ticker}\n\n{EVALUATION_LOG_HEADER}\n"
    write_text_atomic(log_path, log_text)
    return log_text


def _already_processed(log_text: str, accession_number: str) -> bool:
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=accession_number)
    return marker in log_text


def _collect_filings_to_scan(
    sec_client: SecFilingsClient,
    ticker: str,
    *,
    log_text: str,
    purchase_date: date | None,
    filings_limit: int,
) -> list[FilingRecord]:
    """Return filings newest-first, bounded by the purchase date and the scan limit.

    The limit bounds the first run. Once the log has entries, the scan continues past
    the limit until it reaches an already-processed filing, so a backlog larger than
    the limit is not silently dropped.
    """
    has_history = PROCESSED_MARKER_PREFIX in log_text
    scanned: list[FilingRecord] = []
    for filing in sec_client.iter_filings(ticker, forms=SUPPORTED_FORMS, include_amendments=False):
        if purchase_date and _filing_date_as_date(filing.filing_date) < purchase_date:
            break
        if len(scanned) >= filings_limit and (
            not has_history or _already_processed(log_text, filing.accession_number)
        ):
            break
        scanned.append(filing)
    return scanned


def _append_evaluation_log_entry(
    log_text: str,
    filing: FilingRecord,
    evaluation_markdown: str,
) -> str:
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=filing.accession_number)
    if marker in log_text:
        return log_text

    title = (
        f"### SEC Filing Review: {filing.form} ({filing.filing_date}) - "
        f"{filing.accession_number}"
    )
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metadata = (
        f"{marker}\n"
        f"- Filing URL: {filing.primary_document_url}\n"
        f"- Processed on: {created_at}\n"
    )
    block = f"{title}\n{metadata}\n{evaluation_markdown.strip()}\n"

    if EVALUATION_LOG_HEADER in log_text:
        return log_text.rstrip() + "\n\n" + block + "\n"

    return log_text.rstrip() + f"\n\n{EVALUATION_LOG_HEADER}\n\n{block}\n"


_PURCHASED_PATTERN = re.compile(
    r"[-*]\s*Purchased\s*:\s*(.+)",
    re.IGNORECASE,
)

_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%d %B %Y")


def _parse_purchase_date(thesis_text: str) -> date | None:
    """Return the earliest purchase date found in the thesis Position section, or None."""
    earliest: date | None = None
    for match in _PURCHASED_PATTERN.finditer(thesis_text):
        raw = match.group(1).strip()
        for fmt in _DATE_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt).date()
                if earliest is None or parsed < earliest:
                    earliest = parsed
                break
            except ValueError:
                continue
    return earliest


def _filing_date_as_date(filing_date: str) -> date:
    """Parse a YYYY-MM-DD filing date string into a date object."""
    return datetime.strptime(filing_date, "%Y-%m-%d").date()


def _thesis_fingerprint(thesis_text: str) -> str:
    """SHA-256 of the thesis, ignoring line-ending and trailing-whitespace differences."""
    normalized = "\n".join(line.rstrip() for line in thesis_text.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _recorded_thesis_fingerprint(log_text: str) -> str | None:
    match = THESIS_FINGERPRINT_RE.search(log_text)
    return match.group(1) if match else None


def _set_thesis_fingerprint(log_text: str, fingerprint: str) -> str:
    marker = THESIS_FINGERPRINT_TEMPLATE.format(fingerprint=fingerprint)
    if THESIS_FINGERPRINT_RE.search(log_text):
        return THESIS_FINGERPRINT_RE.sub(marker, log_text, count=1)

    lines = log_text.splitlines()
    heading_idx = next((i for i, line in enumerate(lines) if line.startswith("# ")), -1)
    lines.insert(heading_idx + 1, marker)
    return "\n".join(lines) + ("\n" if log_text.endswith("\n") else "")


def _latest_periodic_filing(sec_client: SecFilingsClient, ticker: str) -> FilingRecord | None:
    for filing in sec_client.iter_filings(ticker, forms=PERIODIC_FORMS, include_amendments=False):
        return filing
    return None


def _review_thesis_change(
    *,
    ticker: str,
    thesis_text: str,
    log_text: str,
    log_path: Path,
    sec_client: SecFilingsClient,
    evaluator: OpenAIThesisEvaluator,
    instruction_texts: dict[str, str],
    periodic_reviewed_this_run: bool,
) -> tuple[str, bool]:
    """Re-review the latest 10-K/10-Q when the thesis was edited since the last run.

    Logs written before fingerprints existed only get a baseline fingerprint, so
    upgrading does not trigger a review for every thesis.
    """
    fingerprint = _thesis_fingerprint(thesis_text)
    recorded = _recorded_thesis_fingerprint(log_text)
    if recorded == fingerprint:
        return log_text, False

    reviewed = False
    if recorded is None:
        print("- Thesis fingerprint recorded (later edits will trigger a re-review)")
    elif periodic_reviewed_this_run:
        print("- Thesis changed; already reviewed against a new 10-K/10-Q in this run")
    else:
        print("- Thesis changed since the last run; re-reviewing the latest 10-K/10-Q")
        filing = _latest_periodic_filing(sec_client, ticker)
        marker = (
            REVISION_MARKER_TEMPLATE.format(fingerprint=fingerprint[:12], accession=filing.accession_number)
            if filing
            else None
        )
        if filing is None:
            print("  - No 10-K/10-Q available for a revision review")
        elif marker not in log_text:
            print(f"  - Evaluating {filing.form} filed {filing.filing_date} ({filing.accession_number})")
            filing_doc = sec_client.fetch_document(filing)
            evaluation = evaluator.evaluate(
                EvaluationInput(
                    ticker=ticker,
                    form=filing.form,
                    filing_date=filing.filing_date,
                    accession_number=filing.accession_number,
                    filing_url=filing.primary_document_url,
                    instruction_text=instruction_texts[filing.form],
                    thesis_text=thesis_text,
                    filing_text=filing_doc.text,
                    review_note=REVISION_REVIEW_NOTE,
                )
            )
            log_text = _append_revision_entry(log_text, filing, evaluation, fingerprint)
            print(f"    {first_content_line(evaluation)}")
            reviewed = True

    # Only record the new fingerprint once the review succeeded, so failures are retried.
    log_text = _set_thesis_fingerprint(log_text, fingerprint)
    write_text_atomic(log_path, log_text)
    return log_text, reviewed


def _append_revision_entry(
    log_text: str,
    filing: FilingRecord,
    evaluation_markdown: str,
    fingerprint: str,
) -> str:
    marker = REVISION_MARKER_TEMPLATE.format(fingerprint=fingerprint[:12], accession=filing.accession_number)
    title = (
        f"### Thesis Revision Review: {filing.form} ({filing.filing_date}) - "
        f"{filing.accession_number}"
    )
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metadata = (
        f"{marker}\n"
        f"- Filing URL: {filing.primary_document_url}\n"
        f"- Processed on: {created_at}\n"
        f"- Thesis fingerprint: {fingerprint[:12]}\n"
    )
    block = f"{title}\n{metadata}\n{evaluation_markdown.strip()}\n"
    if EVALUATION_LOG_HEADER in log_text:
        return log_text.rstrip() + "\n\n" + block + "\n"
    return log_text.rstrip() + f"\n\n{EVALUATION_LOG_HEADER}\n\n{block}\n"


def _update_status_file_if_needed(
    *,
    ticker: str,
    log_text: str,
    status_path: Path,
    evaluator: OpenAIThesisEvaluator,
    status_instruction_text: str,
) -> bool:
    latest = _latest_relevant_entry(log_text)
    if latest is None:
        return False

    existing_text = None
    existing_source = None
    leverage_block = None
    if status_path.exists():
        existing_text = status_path.read_text(encoding="utf-8")
        existing_source = _extract_status_source_accession(existing_text)
        leverage_block = extract_leverage_block(existing_text)
    if existing_source == latest["key"]:
        return False

    # The leverage block is owned by leverage-evaluator.py; keep it out of the model's
    # hands and re-insert it unchanged after the status is regenerated.
    updated_on = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    status_text = evaluator.render_status_markdown(
        ticker=ticker,
        filing_form=_source_form_label(latest),
        filing_date=latest["filing_date"],
        accession_number=latest["accession"],
        evaluation_markdown=latest["evaluation"],
        status_instruction_text=status_instruction_text,
        updated_on=updated_on,
        previous_status_markdown=remove_leverage_blocks(existing_text) if existing_text else None,
    )

    if VERDICT_LINE_RE.search(status_text):
        status_text = _enforce_status_metadata(
            status_text, ticker=ticker, latest=latest, updated_on=updated_on
        )
    else:
        # Not a usable status document; build one from the evaluation's own verdict.
        status_text = _fallback_status_text(ticker=ticker, latest=latest, updated_on=updated_on)

    status_text = remove_leverage_blocks(status_text)
    if leverage_block:
        merged = insert_leverage_block(status_text, leverage_block)
        if merged is None:
            merged = status_text.rstrip() + "\n\n" + "\n".join(leverage_block)
        status_text = merged

    write_text_atomic(status_path, status_text.rstrip() + "\n")
    return True


def _source_form_label(latest: dict[str, str]) -> str:
    if latest.get("kind") == "revision":
        return f"{latest['form']} (thesis revision review)"
    return latest["form"]


def _enforce_status_metadata(
    status_text: str,
    *,
    ticker: str,
    latest: dict[str, str],
    updated_on: str,
) -> str:
    """Make the source marker and 'Updated on' date authoritative, whatever the model wrote."""
    marker = STATUS_SOURCE_MARKER_TEMPLATE.format(accession=latest["key"])
    lines = STATUS_SOURCE_MARKER_RE.sub("", status_text).splitlines()

    heading_idx = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if heading_idx is None:
        lines = [f"# {ticker} Thesis Status", ""] + lines
        heading_idx = 0
    # Drop blank lines left where the old marker was, then re-insert below the heading.
    insert_at = heading_idx + 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        lines.pop(insert_at)
    lines[insert_at:insert_at] = ["", marker]

    text = "\n".join(lines)
    updated_line = f"- Updated on: {updated_on}"
    if UPDATED_ON_RE.search(text):
        return UPDATED_ON_RE.sub(lambda m: f"{m.group(1)} {updated_on}", text, count=1)

    lines = text.splitlines()
    source_idx = next(
        (i for i, line in enumerate(lines) if line.strip().lower().startswith("- source filing:")),
        lines.index(marker),
    )
    lines.insert(source_idx + 1, updated_line)
    return "\n".join(lines)


def _fallback_status_text(*, ticker: str, latest: dict[str, str], updated_on: str) -> str:
    verdict = _extract_verdict(latest["evaluation"])
    overall = VERDICT_STATUS_COLORS.get(verdict or "", "Unknown")
    if verdict is None:
        validity = "Unknown"
    else:
        validity = "Broken" if verdict == "Exit" else "Intact"
    return "\n".join(
        [
            f"# {ticker} Thesis Status",
            "",
            STATUS_SOURCE_MARKER_TEMPLATE.format(accession=latest["key"]),
            f"- Source filing: {_source_form_label(latest)} ({latest['filing_date']}) - {latest['accession']}",
            f"- Updated on: {updated_on}",
            f"- Overall status: {overall}",
            f"- Verdict: {verdict or 'Unknown'}",
            f"- Thesis validity: {validity}",
            "- Note: status rendering failed; derived from the evaluation's verdict. See the log entry.",
            "",
            "## Parts",
            f"- Filing impact: {overall}",
            "",
            "## Latest assessment",
            f"- {first_content_line(latest['evaluation'])}",
        ]
    )


def _extract_status_source_accession(status_text: str) -> str | None:
    prefix = "<!-- status-source-accession:"
    for line in status_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix) and stripped.endswith("-->"):
            return stripped[len(prefix) : -3].strip()
    return None


def _latest_relevant_entry(log_text: str) -> dict[str, str] | None:
    entries = _parse_log_entries(log_text)
    if not entries:
        return None

    relevant = [
        (index, entry) for index, entry in enumerate(entries) if _entry_is_relevant_for_status(entry)
    ]
    if not relevant:
        return None

    # Filing reviews are ordered by filing date; a thesis revision review counts from the
    # day it was written, so it supersedes reviews done against the old thesis.
    relevant.sort(
        key=lambda item: (
            item[1]["effective_date"],
            1 if item[1]["kind"] == "revision" else 0,
            item[1]["accession"] if item[1]["kind"] == "filing" else "",
            item[0],
        )
    )
    return relevant[-1][1]


def _parse_log_entries(log_text: str) -> list[dict[str, str]]:
    matches = list(LOG_ENTRY_HEADER_RE.finditer(log_text))
    entries: list[dict[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(log_text)
        block = log_text[start:end].strip()
        kind = "revision" if match.group(1) == "Thesis Revision Review" else "filing"
        form, filing_date, accession = match.group(2), match.group(3), match.group(4)

        key = accession
        effective_date = filing_date
        if kind == "revision":
            fingerprint = REVISION_FINGERPRINT_RE.search(block)
            processed_on = PROCESSED_ON_RE.search(block)
            key = f"{accession}+thesis-{fingerprint.group(1) if fingerprint else 'revised'}"
            effective_date = processed_on.group(1) if processed_on else filing_date

        entries.append(
            {
                "kind": kind,
                "form": form,
                "filing_date": filing_date,
                "accession": accession,
                "key": key,
                "effective_date": effective_date,
                "evaluation": _extract_evaluation_text_from_block(block),
            }
        )
    return entries


def _extract_evaluation_text_from_block(block: str) -> str:
    lines = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if stripped.startswith(("<!-- processed-sec-filing:", "<!-- thesis-revision-review:")):
            continue
        if stripped.lower().startswith(("- filing url:", "- processed on:", "- thesis fingerprint:")):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _entry_is_relevant_for_status(entry: dict[str, str]) -> bool:
    if entry["form"] in ("10-K", "10-Q"):
        return True

    verdict = _extract_verdict(entry["evaluation"])
    if verdict and verdict != "No Action":
        return True

    return not _is_non_impactful_8k_language(entry["evaluation"])


def _extract_verdict(text: str) -> str | None:
    """Return the first allowed verdict (e.g. 'Watch') found on a 'Verdict:' line."""
    pattern = re.compile(
        r"^(" + "|".join(v.lower() for v in ALLOWED_VERDICTS) + r")\b"
    )
    for line in text.splitlines():
        if "verdict" not in line.lower() or ":" not in line:
            continue
        _, right = line.split(":", 1)
        cleaned = re.sub(r"[^A-Za-z ]", " ", right)
        cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
        match = pattern.match(cleaned)
        if match:
            return next(v for v in ALLOWED_VERDICTS if v.lower() == match.group(1))
    return None


def _is_non_impactful_8k_language(text: str) -> bool:
    lowered = text.lower()
    phrases = (
        "informational",
        "does not affect",
        "no impact",
        "no immediate impact",
        "does not necessitate",
        "no action",
    )
    return any(phrase in lowered for phrase in phrases)


if __name__ == "__main__":
    raise SystemExit(main())