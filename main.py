from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from openai_evaluator import EvaluationInput, OpenAIEvaluatorError, OpenAIThesisEvaluator
from sec_filings import SUPPORTED_FORMS, FilingRecord, SecEdgarError, SecFilingsClient


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
EVALUATION_LOG_HEADER = "## Evaluation Log"
STATUS_SOURCE_MARKER_TEMPLATE = "<!-- status-source-accession:{accession} -->"


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
        help="Max recent SEC filings to scan per thesis ticker. Default: 25",
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
    return parser


def main() -> int:
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
    skipped_count = 0
    failed_count = 0

    for thesis_path in thesis_files:
        print(f"Working on thesis: {thesis_path.name}")
        try:
            thesis_text = thesis_path.read_text(encoding="utf-8")
            ticker = _ticker_from_thesis_path(thesis_path)
            log_path = log_dir / thesis_path.name
            log_text = _load_or_initialize_log(log_path, ticker)

            purchase_date = _parse_purchase_date(thesis_text)
            if purchase_date:
                print(f"- Position purchase date: {purchase_date} (filtering earlier filings)")

            filings = sec_client.list_filings(
                ticker,
                forms=SUPPORTED_FORMS,
                include_amendments=False,
                limit=args.filings_limit,
            )
            print(f"- SEC filings discovered: {len(filings)}")

            if purchase_date:
                filings = [
                    f for f in filings
                    if _filing_date_as_date(f.filing_date) >= purchase_date
                ]
                print(f"- SEC filings after purchase date: {len(filings)}")

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
                print()
                skipped_count += 1
                continue

            print(f"- New filings available: {len(new_filings)}")

            for filing in new_filings:
                print(
                    f"  - Evaluating {filing.form} filed {filing.filing_date} "
                    f"({filing.accession_number})"
                )

                instruction_text = instruction_texts.get(filing.form)
                if not instruction_text:
                    print(f"    Skipped: no instruction file configured for {filing.form}")
                    continue

                filing_doc = sec_client.fetch_filing(
                    ticker,
                    accession_number=filing.accession_number,
                )

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
                    )
                )

                log_text = _append_evaluation_log_entry(log_text, filing, evaluation)
                log_path.write_text(log_text, encoding="utf-8")

                print("    Result summary:")
                first_line = _first_content_line(evaluation)
                print(f"    {first_line}")
                processed_count += 1

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
                print("- Status unchanged (no newer relevant filing)")

            print()
        except (SecEdgarError, OpenAIEvaluatorError, ValueError, FileNotFoundError) as exc:
            print(f"- Failed: {exc}", file=sys.stderr)
            print()
            failed_count += 1
        except Exception as exc:
            print(f"- Unexpected error: {exc}", file=sys.stderr)
            print()
            failed_count += 1

    print("Run complete")
    print(f"- Filings processed: {processed_count}")
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


def _ticker_from_thesis_path(thesis_path: Path) -> str:
    ticker = thesis_path.stem.strip().upper()
    if not ticker:
        raise ValueError(f"Could not derive ticker from thesis file name: {thesis_path}")
    return ticker


def _load_or_initialize_log(log_path: Path, ticker: str) -> str:
    if log_path.exists():
        return log_path.read_text(encoding="utf-8")

    # Initialize a new log from the ticker/file name, not thesis markdown headers.
    log_text = f"# {ticker}\n\n{EVALUATION_LOG_HEADER}\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    return log_text


def _already_processed(log_text: str, accession_number: str) -> bool:
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=accession_number)
    return marker in log_text


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


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return "(no content)"


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
    if status_path.exists():
        existing_text = status_path.read_text(encoding="utf-8")
        existing_source = _extract_status_source_accession(existing_text)
    if existing_source == latest["accession"]:
        return False

    status_text = evaluator.render_status_markdown(
        ticker=ticker,
        filing_form=latest["form"],
        filing_date=latest["filing_date"],
        accession_number=latest["accession"],
        evaluation_markdown=latest["evaluation"],
        status_instruction_text=status_instruction_text,
        previous_status_markdown=existing_text,
    )

    # Guard against malformed responses by enforcing the status source marker.
    required_marker = STATUS_SOURCE_MARKER_TEMPLATE.format(accession=latest["accession"])
    if required_marker not in status_text:
        status_text = "\n".join(
            [
                f"# {ticker} Thesis Status",
                "",
                required_marker,
                f"- Source filing: {latest['form']} ({latest['filing_date']}) - {latest['accession']}",
                f"- Updated on: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                "- Overall status: Yellow",
                "- Verdict: Watch",
                "- Thesis validity: Intact",
                "",
                "## Parts",
                "- Filing impact: Yellow",
                "",
                "## Latest assessment",
                f"- {_first_content_line(latest['evaluation'])}",
            ]
        )

    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(status_text.rstrip() + "\n", encoding="utf-8")
    return True


def _extract_status_source_accession(status_text: str) -> str | None:
    prefix = "<!-- status-source-accession:"
    for line in status_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix) and stripped.endswith("-->"):
            return stripped[len(prefix) : -3]
    return None


def _latest_relevant_entry(log_text: str) -> dict[str, str] | None:
    entries = _parse_log_entries(log_text)
    if not entries:
        return None

    relevant = [entry for entry in entries if _entry_is_relevant_for_status(entry)]
    if not relevant:
        return None

    relevant.sort(
        key=lambda entry: (
            entry["filing_date"],
            entry["accession"],
        )
    )
    return relevant[-1]


def _parse_log_entries(log_text: str) -> list[dict[str, str]]:
    header_re = re.compile(
        r"^### SEC Filing Review:\s*(10-K|10-Q|8-K)\s*\((\d{4}-\d{2}-\d{2})\)\s*-\s*([0-9-]+)\s*$",
        re.MULTILINE,
    )
    matches = list(header_re.finditer(log_text))
    entries: list[dict[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(log_text)
        block = log_text[start:end].strip()
        evaluation = _extract_evaluation_text_from_block(block)
        entries.append(
            {
                "form": match.group(1),
                "filing_date": match.group(2),
                "accession": match.group(3),
                "evaluation": evaluation,
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
        if stripped.startswith("<!-- processed-sec-filing:"):
            continue
        if stripped.lower().startswith("- filing url:"):
            continue
        if stripped.lower().startswith("- processed on:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _entry_is_relevant_for_status(entry: dict[str, str]) -> bool:
    if entry["form"] in ("10-K", "10-Q"):
        return True

    verdict = _extract_verdict(entry["evaluation"])
    if verdict and verdict.upper() != "NO ACTION":
        return True

    return not _is_non_impactful_8k_language(entry["evaluation"])


def _extract_verdict(text: str) -> str | None:
    for line in text.splitlines():
        if "verdict" not in line.lower() or ":" not in line:
            continue
        _, right = line.split(":", 1)
        cleaned = re.sub(r"[^A-Za-z ]", " ", right)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            return cleaned.title()
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