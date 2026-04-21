from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from openai_evaluator import EvaluationInput, OpenAIEvaluatorError, OpenAIThesisEvaluator
from sec_filings import SUPPORTED_FORMS, FilingRecord, SecEdgarError, SecFilingsClient


ROOT_DIR = Path(__file__).resolve().parent
THESIS_DIR = ROOT_DIR / "thesis"
INSTRUCTIONS_DIR = ROOT_DIR / "instructions"

FORM_INSTRUCTION_FILES = {
    "10-K": "10-k.md",
    "10-Q": "10-q.md",
    "8-K": "8-k.md",
}

PROCESSED_MARKER_TEMPLATE = "<!-- processed-sec-filing:{accession} -->"
DECISION_LOG_HEADER = "## Decision Log"


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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    thesis_dir = Path(args.thesis_dir)
    instructions_dir = Path(args.instructions_dir)

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
    print(f"- Forms: {', '.join(SUPPORTED_FORMS)}")
    print()

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for thesis_path in thesis_files:
        print(f"Working on thesis: {thesis_path.name}")
        try:
            thesis_text = thesis_path.read_text(encoding="utf-8")
            ticker = _ticker_from_thesis_path(thesis_path)

            filings = sec_client.list_filings(
                ticker,
                forms=SUPPORTED_FORMS,
                include_amendments=False,
                limit=args.filings_limit,
            )
            print(f"- SEC filings discovered: {len(filings)}")

            new_filings = [
                filing
                for filing in filings
                if not _already_processed(thesis_text, filing.accession_number)
            ]
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

                thesis_text = _append_decision_log_entry(thesis_text, filing, evaluation)
                thesis_path.write_text(thesis_text, encoding="utf-8")

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


def _already_processed(thesis_text: str, accession_number: str) -> bool:
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=accession_number)
    return marker in thesis_text


def _append_decision_log_entry(
    thesis_text: str,
    filing: FilingRecord,
    evaluation_markdown: str,
) -> str:
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=filing.accession_number)
    if marker in thesis_text:
        return thesis_text

    title = (
        f"### SEC Filing Review: {filing.form} ({filing.filing_date}) - "
        f"{filing.accession_number}"
    )
    created_at = datetime.utcnow().strftime("%Y-%m-%d")
    metadata = (
        f"{marker}\n"
        f"- Filing URL: {filing.primary_document_url}\n"
        f"- Processed on: {created_at}\n"
    )
    block = f"{title}\n{metadata}\n{evaluation_markdown.strip()}\n"

    if DECISION_LOG_HEADER in thesis_text:
        return thesis_text.rstrip() + "\n\n" + block + "\n"

    return thesis_text.rstrip() + f"\n\n{DECISION_LOG_HEADER}\n\n{block}\n"


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "(no content)"


if __name__ == "__main__":
    raise SystemExit(main())