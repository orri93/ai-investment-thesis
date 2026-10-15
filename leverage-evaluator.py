from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai_evaluator import (
    LeverageMetrics,
    OpenAILeverageError,
    OpenAILeverageEvaluator,
    leverage_category,
)

from sec_filings import FilingRecord, SecEdgarError, SecFilingsClient
from status_file import (
    LEVERAGE_STATUS_END_MARKER,
    LEVERAGE_STATUS_START_MARKER,
    extract_leverage_block,
    insert_leverage_block,
)


ROOT_DIR = Path(__file__).resolve().parent
THESIS_DIR = ROOT_DIR / "thesis"
LEVERAGE_DIR = ROOT_DIR / "leverage"
INSTRUCTIONS_DIR = ROOT_DIR / "instructions"
STATUS_DIR = ROOT_DIR / "status"

LEVERAGE_FORMS = ("10-K", "10-Q")
LEVERAGE_INSTRUCTION_FILE = "leverage.md"

PROCESSED_MARKER_TEMPLATE = "<!-- processed-leverage-filing:{accession} -->"
LEVERAGE_LOG_HEADER = "## Leverage Evaluation Log"
LEVERAGE_ENTRY_HEADER_PREFIX = "### Leverage Review:"
LEVERAGE_REPORT_HEADER = "#### Leverage Evaluation Report"
LEVERAGE_EXTRACTION_HEADER = "#### Extraction JSON"
RATIO_LABELS = {
    "Debt-to-Equity": "debt_to_equity",
    "Debt-to-Assets": "debt_to_assets",
    "Net Debt / EBITDA": "net_debt_to_ebitda",
    "Interest Coverage (EBIT / Interest Expense)": "interest_coverage",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate leverage evaluation reports from the latest 10-K/10-Q filing "
            "for each thesis ticker."
        )
    )
    parser.add_argument(
        "--thesis-dir",
        default=str(THESIS_DIR),
        help=f"Path to thesis markdown files. Default: {THESIS_DIR}",
    )
    parser.add_argument(
        "--leverage-dir",
        default=str(LEVERAGE_DIR),
        help=f"Path to leverage report markdown files. Default: {LEVERAGE_DIR}",
    )
    parser.add_argument(
        "--instructions-dir",
        default=str(INSTRUCTIONS_DIR),
        help=f"Path to instruction markdown files. Default: {INSTRUCTIONS_DIR}",
    )
    parser.add_argument(
        "--status-dir",
        default=str(STATUS_DIR),
        help=f"Path to thesis status markdown files. Default: {STATUS_DIR}",
    )
    parser.add_argument(
        "--filings-limit",
        type=int,
        default=25,
        help="Max recent 10-K/10-Q filings to scan per ticker when selecting latest.",
    )
    parser.add_argument(
        "--openai-model",
        default=None,
        help="Optional override for OpenAI model.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    thesis_dir = Path(args.thesis_dir)
    leverage_dir = Path(args.leverage_dir)
    instructions_dir = Path(args.instructions_dir)
    status_dir = Path(args.status_dir)

    try:
        instruction_text = _load_instruction_text(instructions_dir)
        sec_client = SecFilingsClient()
        evaluator = OpenAILeverageEvaluator(model=args.openai_model)
    except (SecEdgarError, OpenAILeverageError, FileNotFoundError, ValueError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
        return 1

    thesis_files = sorted(thesis_dir.glob("*.md"))
    if not thesis_files:
        print(f"No thesis files found in: {thesis_dir}")
        return 0

    leverage_dir.mkdir(parents=True, exist_ok=True)

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    print("Leverage evaluation run started")
    print(f"- Thesis files: {len(thesis_files)}")
    print(f"- Leverage output directory: {leverage_dir}")
    print(f"- Status directory: {status_dir} (existing files only)")
    print("- SEC forms considered: 10-K, 10-Q (latest only)")
    print()

    for thesis_path in thesis_files:
        ticker = _ticker_from_thesis_path(thesis_path)
        leverage_path = leverage_dir / thesis_path.name
        print(f"Working on ticker: {ticker}")

        try:
            leverage_log_text = _load_or_initialize_leverage_log(leverage_path, ticker)
            latest_filing = _latest_relevant_filing(
                sec_client,
                ticker,
                filings_limit=args.filings_limit,
            )

            if latest_filing is None:
                print("- No 10-K/10-Q filings found")
                print()
                skipped_count += 1
                continue

            if _already_processed(leverage_log_text, latest_filing.accession_number):
                print(
                    f"- Latest filing already processed: "
                    f"{latest_filing.form} {latest_filing.filing_date} "
                    f"({latest_filing.accession_number})"
                )
                status_path = status_dir / thesis_path.name
                if _restore_leverage_status_if_missing(
                    status_path=status_path,
                    leverage_log_text=leverage_log_text,
                    filing=latest_filing,
                ):
                    print(f"- Status leverage block restored: {status_path.name}")
                print()
                skipped_count += 1
                continue

            print(
                f"- Evaluating latest filing: {latest_filing.form} "
                f"{latest_filing.filing_date} ({latest_filing.accession_number})"
            )

            filing_document = sec_client.fetch_filing(
                ticker,
                accession_number=latest_filing.accession_number,
            )

            metrics, calculated, report, extraction_raw = evaluator.evaluate(
                ticker=ticker,
                filing=latest_filing,
                filing_text=filing_document.text,
                instruction_text=instruction_text,
            )

            leverage_log_text = _append_leverage_entry(
                leverage_log_text,
                filing=latest_filing,
                metrics=metrics,
                calculated=calculated,
                report_markdown=report,
                extraction_raw=extraction_raw,
            )
            leverage_path.write_text(leverage_log_text, encoding="utf-8")

            status_path = status_dir / thesis_path.name
            status_updated = _append_leverage_to_existing_status(
                status_path=status_path,
                filing=latest_filing,
                calculated=calculated,
                report_markdown=report,
            )

            print("- Leverage report appended")
            if status_updated:
                print(f"- Status updated: {status_path.name}")
            else:
                print("- Status update skipped (missing status file or section)")
            print()
            processed_count += 1

        except (SecEdgarError, OpenAILeverageError, ValueError, FileNotFoundError) as exc:
            print(f"- Failed: {exc}", file=sys.stderr)
            print()
            failed_count += 1
        except Exception as exc:
            print(f"- Unexpected error: {exc}", file=sys.stderr)
            print()
            failed_count += 1

    print("Run complete")
    print(f"- Tickers processed: {processed_count}")
    print(f"- Tickers skipped: {skipped_count}")
    print(f"- Tickers failed: {failed_count}")
    return 0 if failed_count == 0 else 1


def _load_instruction_text(instructions_dir: Path) -> str:
    path = instructions_dir / LEVERAGE_INSTRUCTION_FILE
    if not path.exists():
        raise FileNotFoundError(f"Missing instruction file: {path}")
    return path.read_text(encoding="utf-8").strip()


def _latest_relevant_filing(
    sec_client: SecFilingsClient,
    ticker: str,
    *,
    filings_limit: int,
) -> FilingRecord | None:
    filings = sec_client.list_filings(
        ticker,
        forms=LEVERAGE_FORMS,
        include_amendments=False,
        limit=filings_limit,
    )
    if not filings:
        return None

    return max(
        filings,
        key=lambda filing: (
            filing.filing_date,
            filing.acceptance_datetime or "",
            filing.accession_number,
        ),
    )


def _ticker_from_thesis_path(thesis_path: Path) -> str:
    ticker = thesis_path.stem.strip().upper()
    if not ticker:
        raise ValueError(f"Could not derive ticker from thesis file name: {thesis_path}")
    return ticker


def _load_or_initialize_leverage_log(leverage_path: Path, ticker: str) -> str:
    if leverage_path.exists():
        return leverage_path.read_text(encoding="utf-8")

    leverage_text = f"# {ticker}\n\n{LEVERAGE_LOG_HEADER}\n"
    leverage_path.parent.mkdir(parents=True, exist_ok=True)
    leverage_path.write_text(leverage_text, encoding="utf-8")
    return leverage_text


def _already_processed(log_text: str, accession_number: str) -> bool:
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=accession_number)
    return marker in log_text


def _append_leverage_entry(
    log_text: str,
    *,
    filing: FilingRecord,
    metrics: LeverageMetrics,
    calculated: dict[str, float | None],
    report_markdown: str,
    extraction_raw: str,
) -> str:
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=filing.accession_number)
    if marker in log_text:
        return log_text

    title = (
        f"### Leverage Review: {filing.form} ({filing.filing_date}) - "
        f"{filing.accession_number}"
    )
    processed_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metadata = (
        f"{marker}\n"
        f"- Filing URL: {filing.primary_document_url}\n"
        f"- Processed on: {processed_at}\n"
    )

    extracted_block = _format_extracted_values(metrics)
    ratios_block = _format_ratio_values(calculated)
    raw_extraction_block = (
        "#### Extraction JSON\n\n"
        "```json\n"
        f"{_safe_pretty_json(extraction_raw)}\n"
        "```\n"
    )

    block = (
        f"{title}\n"
        f"{metadata}\n"
        f"{extracted_block}\n"
        f"{ratios_block}\n"
        "#### Leverage Evaluation Report\n\n"
        f"{report_markdown.strip()}\n\n"
        f"{raw_extraction_block}"
    )

    if LEVERAGE_LOG_HEADER in log_text:
        return log_text.rstrip() + "\n\n" + block + "\n"

    return log_text.rstrip() + f"\n\n{LEVERAGE_LOG_HEADER}\n\n{block}\n"


def _format_extracted_values(metrics: LeverageMetrics) -> str:
    rows = [
        ("Company Name", metrics.company_name),
        ("Period End", metrics.period_end),
        ("Currency", metrics.currency),
        ("Total Debt", _fmt_number(metrics.total_debt)),
        ("Shareholders' Equity", _fmt_number(metrics.shareholders_equity)),
        ("Total Assets", _fmt_number(metrics.total_assets)),
        ("Net Debt", _fmt_number(metrics.net_debt)),
        ("EBITDA", _fmt_number(metrics.ebitda)),
        ("EBIT", _fmt_number(metrics.ebit)),
        ("Interest Expense", _fmt_number(metrics.interest_expense)),
        ("Flow Period (months)", metrics.flow_period_months),
        ("Fixed Cost Notes", metrics.fixed_cost_notes),
    ]

    lines = [
        "#### Extracted Values",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for metric, value in rows:
        lines.append(f"| {metric} | {_escape_table(value)} |")
    return "\n".join(lines)


def _format_ratio_values(calculated: dict[str, float | None]) -> str:
    nd_to_ebitda = calculated.get("net_debt_to_ebitda")
    interest_coverage = calculated.get("interest_coverage")
    category = leverage_category(calculated)

    rows = [
        ("Debt-to-Equity", _fmt_ratio(calculated.get("debt_to_equity"))),
        ("Debt-to-Assets", _fmt_ratio(calculated.get("debt_to_assets"))),
        ("EBITDA (annualized)", _fmt_number(calculated.get("ebitda_annualized"))),
        ("Net Debt / EBITDA", _fmt_ratio(nd_to_ebitda)),
        ("Interest Coverage (EBIT / Interest Expense)", _fmt_ratio(interest_coverage)),
        ("Category (rule-based)", category),
    ]

    lines = [
        "#### Calculated Leverage Ratios",
        "",
        "| Ratio | Value |",
        "|---|---|",
    ]
    for ratio, value in rows:
        lines.append(f"| {ratio} | {_escape_table(value)} |")
    return "\n".join(lines)


def _safe_pretty_json(text: str) -> str:
    candidate = _extract_json_object(text)
    try:
        return json.dumps(json.loads(candidate), indent=2)
    except Exception:
        return text


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]

    raise OpenAILeverageError("OpenAI extraction did not return a JSON object.")


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}x"


def _escape_table(value: object) -> str:
    if value is None:
        return "N/A"
    return str(value).replace("|", "\\|")


def _append_leverage_to_existing_status(
    *,
    status_path: Path,
    filing: FilingRecord,
    calculated: dict[str, float | None],
    report_markdown: str,
) -> bool:
    if not status_path.exists():
        return False

    status_text = status_path.read_text(encoding="utf-8")
    updated_status = _append_leverage_block_in_latest_assessment(
        status_text=status_text,
        filing=filing,
        calculated=calculated,
        report_markdown=report_markdown,
    )
    if updated_status is None or updated_status == status_text:
        return False

    status_path.write_text(updated_status, encoding="utf-8")
    return True


def _append_leverage_block_in_latest_assessment(
    *,
    status_text: str,
    filing: FilingRecord,
    calculated: dict[str, float | None],
    report_markdown: str,
) -> str | None:
    leverage_block = _build_leverage_status_block(
        filing=filing,
        calculated=calculated,
        report_markdown=report_markdown,
    )
    return insert_leverage_block(status_text, leverage_block)


def _restore_leverage_status_if_missing(
    *,
    status_path: Path,
    leverage_log_text: str,
    filing: FilingRecord,
) -> bool:
    """Re-add the leverage block for an already-processed filing if the status file lost it."""
    if not status_path.exists():
        return False

    status_text = status_path.read_text(encoding="utf-8")
    existing_block = extract_leverage_block(status_text)
    if existing_block and any(filing.accession_number in line for line in existing_block):
        return False

    logged = _logged_leverage_entry(leverage_log_text, filing.accession_number)
    if logged is None:
        return False
    calculated, report_markdown = logged

    return _append_leverage_to_existing_status(
        status_path=status_path,
        filing=filing,
        calculated=calculated,
        report_markdown=report_markdown,
    )


def _logged_leverage_entry(
    log_text: str,
    accession_number: str,
) -> tuple[dict[str, float | None], str] | None:
    """Recover calculated ratios and the report markdown for a filing from the leverage log."""
    marker = PROCESSED_MARKER_TEMPLATE.format(accession=accession_number)
    marker_idx = log_text.find(marker)
    if marker_idx == -1:
        return None

    next_entry_idx = log_text.find(f"\n{LEVERAGE_ENTRY_HEADER_PREFIX}", marker_idx)
    entry = log_text[marker_idx : next_entry_idx if next_entry_idx != -1 else len(log_text)]

    report_start = entry.find(LEVERAGE_REPORT_HEADER)
    if report_start == -1:
        return None

    calculated: dict[str, float | None] = {key: None for key in RATIO_LABELS.values()}
    for line in entry[:report_start].splitlines():
        match = re.match(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|$", line.strip())
        if not match or match.group(1) not in RATIO_LABELS:
            continue
        value = match.group(2).rstrip("x").strip()
        try:
            calculated[RATIO_LABELS[match.group(1)]] = float(value)
        except ValueError:
            calculated[RATIO_LABELS[match.group(1)]] = None

    report_start += len(LEVERAGE_REPORT_HEADER)
    report_end = entry.rfind(LEVERAGE_EXTRACTION_HEADER)
    if report_end < report_start:
        report_end = len(entry)
    report_markdown = entry[report_start:report_end].strip()
    return calculated, report_markdown


def _build_leverage_status_block(
    *,
    filing: FilingRecord,
    calculated: dict[str, float | None],
    report_markdown: str,
) -> list[str]:
    updated_on = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nd_to_ebitda = calculated.get("net_debt_to_ebitda")
    interest_coverage = calculated.get("interest_coverage")
    debt_to_equity = calculated.get("debt_to_equity")
    debt_to_assets = calculated.get("debt_to_assets")
    category = leverage_category(calculated)

    verdict = _extract_verdict(report_markdown)
    summary = _first_content_line(report_markdown)
    block = [
        LEVERAGE_STATUS_START_MARKER,
        f"### Latest leverage assessment ({filing.form} {filing.filing_date})",
        f"- Source leverage filing: {filing.form} ({filing.filing_date}) - {filing.accession_number}",
        f"- Leverage updated on: {updated_on}",
        f"- Leverage category: {category}",
        f"- Debt-to-Equity: {_fmt_ratio(debt_to_equity)}",
        f"- Debt-to-Assets: {_fmt_ratio(debt_to_assets)}",
        f"- Net Debt / EBITDA: {_fmt_ratio(nd_to_ebitda)}",
        f"- Interest Coverage: {_fmt_ratio(interest_coverage)}",
        f"- Leverage verdict: {verdict}",
        f"- Leverage evaluator summary: {summary}",
        LEVERAGE_STATUS_END_MARKER,
    ]
    return block


def _extract_verdict(text: str) -> str:
    # The verdict is the report's final line, so search from the end.
    for line in reversed(text.splitlines()):
        lowered = line.lower()
        if "verdict" in lowered or "leverage category:" in lowered:
            cleaned = line.strip()
            cleaned = re.sub(r"^#+\s*", "", cleaned)
            cleaned = cleaned.replace("*", "").replace("_", "")
            cleaned = cleaned.strip(" -—:")
            return cleaned
    return "(no verdict)"


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return "(no content)"


if __name__ == "__main__":
    raise SystemExit(main())
