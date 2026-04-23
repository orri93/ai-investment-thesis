from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai_evaluator import LeverageMetrics, OpenAILeverageError, OpenAILeverageEvaluator

from sec_filings import FilingRecord, SecEdgarError, SecFilingsClient


ROOT_DIR = Path(__file__).resolve().parent
THESIS_DIR = ROOT_DIR / "thesis"
LEVERAGE_DIR = ROOT_DIR / "leverage"
INSTRUCTIONS_DIR = ROOT_DIR / "instructions"

LEVERAGE_FORMS = ("10-K", "10-Q")
LEVERAGE_INSTRUCTION_FILE = "leverage.md"

PROCESSED_MARKER_TEMPLATE = "<!-- processed-leverage-filing:{accession} -->"
LEVERAGE_LOG_HEADER = "## Leverage Evaluation Log"


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

            print("- Leverage report appended")
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
    category = _leverage_category(nd_to_ebitda, interest_coverage)

    rows = [
        ("Debt-to-Equity", _fmt_ratio(calculated.get("debt_to_equity"))),
        ("Debt-to-Assets", _fmt_ratio(calculated.get("debt_to_assets"))),
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


def _leverage_category(
    net_debt_to_ebitda: float | None,
    interest_coverage: float | None,
) -> str:
    if net_debt_to_ebitda is None and interest_coverage is None:
        return "Unknown"

    high_by_nd = net_debt_to_ebitda is not None and net_debt_to_ebitda > 3.5
    high_by_ic = interest_coverage is not None and interest_coverage < 3.5
    if high_by_nd or high_by_ic:
        return "High"

    low_by_nd = net_debt_to_ebitda is not None and net_debt_to_ebitda < 1.5
    low_by_ic = interest_coverage is not None and interest_coverage > 8.0
    if low_by_nd and low_by_ic:
        return "Low"

    return "Moderate"


if __name__ == "__main__":
    raise SystemExit(main())
