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

FORM_INSTRUCTION_FILES = {
    "10-K": "10-k.md",
    "10-Q": "10-q.md",
    "8-K": "8-k.md",
}

PROCESSED_MARKER_TEMPLATE = "<!-- processed-sec-filing:{accession} -->"
EVALUATION_LOG_HEADER = "## Evaluation Log"


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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    thesis_dir = Path(args.thesis_dir)
    instructions_dir = Path(args.instructions_dir)
    log_dir = Path(args.log_dir)

    try:
        instruction_texts = _load_instruction_texts(instructions_dir)
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
    print(f"- Forms: {', '.join(SUPPORTED_FORMS)}")
    print()

    log_dir.mkdir(parents=True, exist_ok=True)

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
        if stripped:
            return stripped
    return "(no content)"


if __name__ == "__main__":
    raise SystemExit(main())