from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from openai import OpenAI

from sec_filings import FilingRecord, SecEdgarError, SecFilingsClient


ROOT_DIR = Path(__file__).resolve().parent
THESIS_DIR = ROOT_DIR / "thesis"
VALUATION_DIR = ROOT_DIR / "valuation"
INSTRUCTIONS_DIR = ROOT_DIR / "instructions"

INSTRUCTION_FILES = {
    "extraction": "valuation-extraction.md",
    "models": "valuation-models.md",
    "qualitative": "valuation-qualitative.md",
    "impact": "valuation-impact.md",
}

DEFAULT_10K_YEARS = 7
DEFAULT_10Q_QUARTERS = 5
DEFAULT_8K_MONTHS = 24


class ValuationError(Exception):
    """Raised when valuation processing fails."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate structured valuation models from SEC filings "
            "for each thesis ticker."
        )
    )
    parser.add_argument(
        "--thesis-dir",
        default=str(THESIS_DIR),
        help=f"Path to thesis markdown files. Default: {THESIS_DIR}",
    )
    parser.add_argument(
        "--valuation-dir",
        default=str(VALUATION_DIR),
        help=f"Path to valuation output markdown files. Default: {VALUATION_DIR}",
    )
    parser.add_argument(
        "--instructions-dir",
        default=str(INSTRUCTIONS_DIR),
        help=f"Path to instruction markdown files. Default: {INSTRUCTIONS_DIR}",
    )
    parser.add_argument(
        "--10k-years",
        type=int,
        default=DEFAULT_10K_YEARS,
        dest="ten_k_years",
        help=f"Number of years of 10-K filings to retrieve. Default: {DEFAULT_10K_YEARS}",
    )
    parser.add_argument(
        "--10q-quarters",
        type=int,
        default=DEFAULT_10Q_QUARTERS,
        dest="ten_q_quarters",
        help=f"Number of quarters of 10-Q filings to retrieve. Default: {DEFAULT_10Q_QUARTERS}",
    )
    parser.add_argument(
        "--8k-months",
        type=int,
        default=DEFAULT_8K_MONTHS,
        dest="eight_k_months",
        help=f"Number of months of 8-K filings to retrieve. Default: {DEFAULT_8K_MONTHS}",
    )
    parser.add_argument(
        "--openai-model",
        default=None,
        help="Optional override for OpenAI model.",
    )
    parser.add_argument(
        "--max-filing-chars",
        type=int,
        default=90000,
        help="Maximum characters per filing excerpt sent to OpenAI.",
    )
    parser.add_argument(
        "--ticker",
        default=None,
        help="Process only this ticker (must have a thesis file).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    thesis_dir = Path(args.thesis_dir)
    valuation_dir = Path(args.valuation_dir)
    instructions_dir = Path(args.instructions_dir)

    try:
        instructions = _load_instructions(instructions_dir)
        sec_client = SecFilingsClient()
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model = args.openai_model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    except (SecEdgarError, FileNotFoundError, ValueError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
        return 1

    thesis_files = sorted(thesis_dir.glob("*.md"))
    if not thesis_files:
        print(f"No thesis files found in: {thesis_dir}")
        return 0

    if args.ticker:
        target = args.ticker.strip().lower()
        thesis_files = [f for f in thesis_files if f.stem.strip().lower() == target]
        if not thesis_files:
            print(f"No thesis file found for ticker: {args.ticker}")
            return 1

    valuation_dir.mkdir(parents=True, exist_ok=True)

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    print("Valuation models run started")
    print(f"- Thesis files: {len(thesis_files)}")
    print(f"- Valuation output directory: {valuation_dir}")
    print(f"- 10-K lookback: {args.ten_k_years} years")
    print(f"- 10-Q lookback: {args.ten_q_quarters} quarters")
    print(f"- 8-K lookback: {args.eight_k_months} months")
    print()

    for thesis_path in thesis_files:
        ticker = _ticker_from_thesis_path(thesis_path)
        valuation_path = valuation_dir / thesis_path.name
        print(f"Working on ticker: {ticker}")

        try:
            # Step 1: Gather SEC filings
            filings = _gather_filings(
                sec_client,
                ticker,
                ten_k_years=args.ten_k_years,
                ten_q_quarters=args.ten_q_quarters,
                eight_k_months=args.eight_k_months,
            )

            if not filings["10-K"] and not filings["10-Q"]:
                print("  - No 10-K or 10-Q filings found, skipping")
                print()
                skipped_count += 1
                continue

            print(
                f"  - Found {len(filings['10-K'])} 10-K, "
                f"{len(filings['10-Q'])} 10-Q, "
                f"{len(filings['8-K'])} 8-K filings"
            )

            # Fetch filing texts
            filing_texts = _fetch_filing_texts(
                sec_client, ticker, filings, max_chars=args.max_filing_chars
            )
            print(f"  - Fetched {len(filing_texts)} filing documents")

            # Step 2: Extract financial data (Step 1 in requirements)
            print("  - Step 1: Extracting financial data...")
            extractions = _step_extract_financials(
                openai_client, model, ticker, filing_texts, instructions["extraction"],
                max_chars=args.max_filing_chars,
            )
            print(f"  - Extracted data from {len(extractions)} filings")

            # Step 3: Build valuation models (Step 2 in requirements)
            print("  - Step 2: Constructing valuation models...")
            valuation_models = _step_valuation_models(
                openai_client, model, ticker, extractions, instructions["models"],
            )

            # Step 4: Qualitative drivers (Step 3 in requirements)
            print("  - Step 3: Assessing qualitative value drivers...")
            qualitative = _step_qualitative_drivers(
                openai_client, model, ticker, filing_texts, extractions,
                valuation_models, instructions["qualitative"],
                max_chars=args.max_filing_chars,
            )

            # Step 5: Filing-to-valuation impact (Step 4 in requirements)
            print("  - Step 4: Connecting filings to valuation impact...")
            impact = _step_valuation_impact(
                openai_client, model, ticker, filing_texts, extractions,
                valuation_models, qualitative, instructions["impact"],
                max_chars=args.max_filing_chars,
            )

            # Assemble and write output
            output = _assemble_valuation_output(
                ticker, filings, extractions, valuation_models, qualitative, impact
            )
            valuation_path.write_text(output, encoding="utf-8")
            print(f"  - Valuation written to: {valuation_path.name}")
            print()
            processed_count += 1

        except (SecEdgarError, ValuationError, ValueError) as exc:
            print(f"  - Failed: {exc}", file=sys.stderr)
            print()
            failed_count += 1
        except Exception as exc:
            print(f"  - Unexpected error: {exc}", file=sys.stderr)
            print()
            failed_count += 1

    print("Run complete")
    print(f"- Tickers processed: {processed_count}")
    print(f"- Tickers skipped: {skipped_count}")
    print(f"- Tickers failed: {failed_count}")
    return 0 if failed_count == 0 else 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_instructions(instructions_dir: Path) -> dict[str, str]:
    instructions = {}
    for key, filename in INSTRUCTION_FILES.items():
        path = instructions_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing instruction file: {path}")
        instructions[key] = path.read_text(encoding="utf-8").strip()
    return instructions


def _ticker_from_thesis_path(thesis_path: Path) -> str:
    ticker = thesis_path.stem.strip().upper()
    if not ticker:
        raise ValueError(f"Could not derive ticker from thesis file name: {thesis_path}")
    return ticker


def _gather_filings(
    sec_client: SecFilingsClient,
    ticker: str,
    *,
    ten_k_years: int,
    ten_q_quarters: int,
    eight_k_months: int,
) -> dict[str, list[FilingRecord]]:
    """Gather relevant filings within the specified lookback windows."""
    now = datetime.now(timezone.utc)
    cutoff_10k = (now - timedelta(days=ten_k_years * 365)).strftime("%Y-%m-%d")
    cutoff_10q = (now - timedelta(days=ten_q_quarters * 92)).strftime("%Y-%m-%d")
    cutoff_8k = (now - timedelta(days=eight_k_months * 31)).strftime("%Y-%m-%d")

    # Fetch generous limits to cover the lookback periods
    all_10k: list[FilingRecord] = []
    for filing in sec_client.iter_filings(ticker, forms=("10-K",), include_amendments=False):
        if filing.filing_date < cutoff_10k:
            break
        all_10k.append(filing)
        if len(all_10k) >= ten_k_years + 2:
            break

    all_10q: list[FilingRecord] = []
    for filing in sec_client.iter_filings(ticker, forms=("10-Q",), include_amendments=False):
        if filing.filing_date < cutoff_10q:
            break
        all_10q.append(filing)
        if len(all_10q) >= ten_q_quarters + 2:
            break

    all_8k: list[FilingRecord] = []
    for filing in sec_client.iter_filings(ticker, forms=("8-K",), include_amendments=False):
        if filing.filing_date < cutoff_8k:
            break
        all_8k.append(filing)
        if len(all_8k) >= 50:  # cap 8-K count to avoid excessive fetching
            break

    return {
        "10-K": all_10k,
        "10-Q": all_10q,
        "8-K": all_8k,
    }


def _fetch_filing_texts(
    sec_client: SecFilingsClient,
    ticker: str,
    filings: dict[str, list[FilingRecord]],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Fetch and prepare filing texts. Returns list of dicts with metadata and text."""
    results: list[dict[str, Any]] = []

    # Prioritize 10-K and 10-Q, limit 8-K to most relevant
    for form_type in ("10-K", "10-Q", "8-K"):
        for filing in filings.get(form_type, []):
            try:
                doc = sec_client.fetch_filing(
                    ticker,
                    accession_number=filing.accession_number,
                )
                text = _prepare_filing_text(doc.text, max_chars=max_chars)
                results.append({
                    "form": filing.form,
                    "filing_date": filing.filing_date,
                    "accession_number": filing.accession_number,
                    "url": filing.primary_document_url,
                    "text": text,
                })
            except SecEdgarError:
                # Skip filings that fail to download
                continue

    return results


def _prepare_filing_text(filing_text: str, *, max_chars: int) -> str:
    """Clean HTML tags and normalize whitespace, then truncate."""
    text = filing_text
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?i)</?(br|p|div|tr|li|h1|h2|h3|h4|h5|h6|table|section)[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    normalized = "\n".join(lines)

    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars]


# ---------------------------------------------------------------------------
# Step 1: Extract financial data from filings
# ---------------------------------------------------------------------------


def _step_extract_financials(
    client: OpenAI,
    model: str,
    ticker: str,
    filing_texts: list[dict[str, Any]],
    instruction_text: str,
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    """Extract structured financial data from each 10-K and 10-Q filing."""
    extractions: list[dict[str, Any]] = []

    # Only extract from 10-K and 10-Q (not 8-K for financial data)
    financial_filings = [f for f in filing_texts if f["form"] in ("10-K", "10-Q")]

    for filing_info in financial_filings:
        system_prompt = (
            "You are a forensic financial analyst. Extract and structure financial "
            "data from SEC filings with high precision. Return strict JSON only."
        )

        user_prompt = (
            f"Ticker: {ticker}\n"
            f"Filing form: {filing_info['form']}\n"
            f"Filing date: {filing_info['filing_date']}\n"
            f"Accession: {filing_info['accession_number']}\n"
            f"Filing URL: {filing_info['url']}\n\n"
            f"Extraction instructions:\n{instruction_text}\n\n"
            f"SEC filing text (may be truncated):\n{filing_info['text'][:max_chars]}"
        )

        try:
            response = _call_openai(client, model, system_prompt, user_prompt)
            extraction_json = _extract_json_from_response(response)
            extraction = json.loads(extraction_json)
            extraction["_filing_form"] = filing_info["form"]
            extraction["_filing_date"] = filing_info["filing_date"]
            extraction["_accession_number"] = filing_info["accession_number"]
            extractions.append(extraction)
        except (json.JSONDecodeError, ValuationError) as exc:
            print(f"    - Warning: extraction failed for {filing_info['form']} "
                  f"{filing_info['filing_date']}: {exc}")
            continue

    return extractions


# ---------------------------------------------------------------------------
# Step 2: Construct valuation models
# ---------------------------------------------------------------------------


def _step_valuation_models(
    client: OpenAI,
    model: str,
    ticker: str,
    extractions: list[dict[str, Any]],
    instruction_text: str,
) -> str:
    """Build DCF, normalized earnings, unit economics, and scenario analyses."""
    system_prompt = (
        "You are a senior equity analyst building rigorous valuation models. "
        "Use only the provided financial data. Produce structured markdown output."
    )

    extractions_summary = json.dumps(extractions, indent=2, default=str)
    # Cap the extractions summary to avoid token overflow
    if len(extractions_summary) > 120000:
        extractions_summary = extractions_summary[:120000] + "\n... [truncated]"

    user_prompt = (
        f"Ticker: {ticker}\n\n"
        f"Valuation model instructions:\n{instruction_text}\n\n"
        f"Structured financial extractions from SEC filings:\n{extractions_summary}\n\n"
        "Build the valuation models as specified in the instructions. "
        "Use the multi-period data to establish trends and make projections."
    )

    return _call_openai(client, model, system_prompt, user_prompt)


# ---------------------------------------------------------------------------
# Step 3: Qualitative value drivers
# ---------------------------------------------------------------------------


def _step_qualitative_drivers(
    client: OpenAI,
    model: str,
    ticker: str,
    filing_texts: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    valuation_models: str,
    instruction_text: str,
    *,
    max_chars: int,
) -> str:
    """Assess qualitative drivers of value from filings and financial data."""
    system_prompt = (
        "You are a strategic analyst evaluating qualitative drivers of company value. "
        "Ground all claims in evidence from the provided SEC filings and financial data."
    )

    # Include a representative sample of filing text for qualitative analysis
    # Prioritize most recent 10-K and a few 8-Ks for qualitative context
    qualitative_context = _build_qualitative_context(filing_texts, max_chars=max_chars // 2)

    extractions_summary = json.dumps(extractions, indent=2, default=str)
    if len(extractions_summary) > 60000:
        extractions_summary = extractions_summary[:60000] + "\n... [truncated]"

    user_prompt = (
        f"Ticker: {ticker}\n\n"
        f"Qualitative assessment instructions:\n{instruction_text}\n\n"
        f"Quantitative valuation model outputs:\n{valuation_models[:30000]}\n\n"
        f"Structured financial extractions:\n{extractions_summary}\n\n"
        f"SEC filing excerpts for qualitative context:\n{qualitative_context}\n\n"
        "Assess the qualitative value drivers as specified in the instructions."
    )

    return _call_openai(client, model, system_prompt, user_prompt)


def _build_qualitative_context(
    filing_texts: list[dict[str, Any]],
    *,
    max_chars: int,
) -> str:
    """Build a representative context from filings for qualitative analysis."""
    parts: list[str] = []
    budget = max_chars

    # Most recent 10-K first (richest qualitative source)
    ten_ks = [f for f in filing_texts if f["form"] == "10-K"]
    if ten_ks:
        excerpt = ten_ks[0]["text"][:budget // 2]
        parts.append(f"[10-K {ten_ks[0]['filing_date']}]\n{excerpt}")
        budget -= len(parts[-1])

    # Recent 8-Ks for event-driven qualitative information
    eight_ks = [f for f in filing_texts if f["form"] == "8-K"]
    per_8k_budget = min(8000, budget // max(len(eight_ks), 1))
    for filing_info in eight_ks[:5]:
        if budget <= 0:
            break
        excerpt = filing_info["text"][:per_8k_budget]
        parts.append(f"[8-K {filing_info['filing_date']}]\n{excerpt}")
        budget -= len(parts[-1])

    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Step 4: Filing-to-valuation impact
# ---------------------------------------------------------------------------


def _step_valuation_impact(
    client: OpenAI,
    model: str,
    ticker: str,
    filing_texts: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    valuation_models: str,
    qualitative: str,
    instruction_text: str,
    *,
    max_chars: int,
) -> str:
    """Connect filing data to valuation impact analysis."""
    system_prompt = (
        "You are a valuation analyst connecting SEC filing data to intrinsic value. "
        "Quantify impacts where possible and produce structured outputs."
    )

    extractions_summary = json.dumps(extractions, indent=2, default=str)
    if len(extractions_summary) > 60000:
        extractions_summary = extractions_summary[:60000] + "\n... [truncated]"

    user_prompt = (
        f"Ticker: {ticker}\n\n"
        f"Impact analysis instructions:\n{instruction_text}\n\n"
        f"Quantitative valuation models:\n{valuation_models[:30000]}\n\n"
        f"Qualitative assessment:\n{qualitative[:20000]}\n\n"
        f"Structured financial extractions:\n{extractions_summary}\n\n"
        "Connect the filings to valuation impact as specified in the instructions. "
        "Reason about margin compression, debt changes, dilution, and other material factors."
    )

    return _call_openai(client, model, system_prompt, user_prompt)


# ---------------------------------------------------------------------------
# OpenAI helpers
# ---------------------------------------------------------------------------


def _call_openai(client: OpenAI, model: str, system_prompt: str, user_prompt: str) -> str:
    """Call OpenAI API with optional web search fallback."""
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "tools": [{"type": "web_search_preview"}],
    }
    try:
        response = client.responses.create(**payload)
    except Exception:
        # Retry without web search tool
        payload.pop("tools", None)
        try:
            response = client.responses.create(**payload)
        except Exception as exc:
            raise ValuationError(f"OpenAI request failed: {exc}") from exc

    text = getattr(response, "output_text", "")
    if not text or not text.strip():
        raise ValuationError("OpenAI returned no text.")
    return text.strip()


def _extract_json_from_response(text: str) -> str:
    """Extract a JSON object from response text."""
    stripped = text.strip()

    # Remove code fences if present
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        stripped = "\n".join(lines).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start:end + 1]

    raise ValuationError("Response did not contain a JSON object.")


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------


def _assemble_valuation_output(
    ticker: str,
    filings: dict[str, list[FilingRecord]],
    extractions: list[dict[str, Any]],
    valuation_models: str,
    qualitative: str,
    impact: str,
) -> str:
    """Assemble the final valuation output markdown document."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    header = (
        f"# {ticker} — Valuation Analysis\n\n"
        f"Generated: {generated_at}\n\n"
        f"**Data Sources:**\n"
        f"- 10-K filings: {len(filings['10-K'])} "
        f"({_date_range(filings['10-K'])})\n"
        f"- 10-Q filings: {len(filings['10-Q'])} "
        f"({_date_range(filings['10-Q'])})\n"
        f"- 8-K filings: {len(filings['8-K'])} "
        f"({_date_range(filings['8-K'])})\n"
        f"- Financial extractions: {len(extractions)} periods\n\n"
        "---\n\n"
    )

    extraction_summary = _format_extraction_summary(extractions)

    sections = [
        header,
        "## Financial Data Extractions (Summary)\n\n",
        extraction_summary,
        "\n\n---\n\n",
        valuation_models,
        "\n\n---\n\n",
        qualitative,
        "\n\n---\n\n",
        impact,
    ]

    return "".join(sections)


def _date_range(filings: list[FilingRecord]) -> str:
    """Return a string showing the date range of filings."""
    if not filings:
        return "none"
    dates = sorted(f.filing_date for f in filings)
    if len(dates) == 1:
        return dates[0]
    return f"{dates[0]} to {dates[-1]}"


def _format_extraction_summary(extractions: list[dict[str, Any]]) -> str:
    """Format a concise summary table of extracted financial data."""
    if not extractions:
        return "*No financial data extracted.*\n"

    lines = [
        "| Period | Form | Revenue | Op. Income | FCF | Total Debt | Net Debt |",
        "|--------|------|---------|------------|-----|------------|----------|",
    ]

    for ext in extractions:
        period = ext.get("period_end") or ext.get("_filing_date", "?")
        form = ext.get("_filing_form", "?")
        rm = ext.get("revenue_margins", {})
        cf = ext.get("cash_flow", {})
        dl = ext.get("debt_liquidity", {})

        revenue = _fmt_millions(rm.get("total_revenue"))
        op_income = _fmt_millions(rm.get("operating_income"))
        fcf = _fmt_millions(cf.get("free_cash_flow"))
        total_debt = _fmt_millions(dl.get("total_debt"))
        net_debt = _fmt_millions(dl.get("net_debt"))

        lines.append(
            f"| {period} | {form} | {revenue} | {op_income} | {fcf} | {total_debt} | {net_debt} |"
        )

    return "\n".join(lines)


def _fmt_millions(value: Any) -> str:
    """Format a number as millions with 1 decimal, or return '—' if None."""
    if value is None:
        return "—"
    try:
        v = float(value)
        if abs(v) >= 1000:
            return f"${v / 1000:.1f}B"
        return f"${v:.0f}M"
    except (TypeError, ValueError):
        return "—"


if __name__ == "__main__":
    sys.exit(main())
