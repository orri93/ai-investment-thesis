from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from filing_text import ExhibitText, build_filing_excerpt, html_to_text
from openai_support import create_openai_client, create_response_text
from sec_filings import FilingRecord

# Thresholds from instructions/leverage.md ("Practical interpretation").
HIGH_NET_DEBT_TO_EBITDA = 3.5
LOW_NET_DEBT_TO_EBITDA = 1.5
HIGH_RISK_INTEREST_COVERAGE = 3.5
LOW_RISK_INTEREST_COVERAGE = 8.0


class OpenAIEvaluatorError(Exception):
    """Raised when thesis evaluation with OpenAI cannot be completed."""


class OpenAILeverageError(Exception):
    """Raised when leverage extraction or reporting with OpenAI fails."""


@dataclass(frozen=True)
class EvaluationInput:
    ticker: str
    form: str
    filing_date: str
    accession_number: str
    filing_url: str
    instruction_text: str
    thesis_text: str
    filing_text: str
    exhibits: tuple[ExhibitText, ...] = ()


class OpenAIThesisEvaluator:
    """Runs form-specific investment thesis evaluations with OpenAI."""

    def __init__(self, model: str | None = None, max_filing_chars: int = 60000):
        self.client = create_openai_client(OpenAIEvaluatorError)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.max_filing_chars = max_filing_chars

    def evaluate(self, payload: EvaluationInput) -> str:
        filing_excerpt = build_filing_excerpt(
            payload.form,
            payload.filing_text,
            payload.exhibits,
            max_chars=self.max_filing_chars,
        )

        system_prompt = (
            "You are a disciplined investment-thesis review assistant. "
            "Follow the supplied instructions exactly, ground claims in the filing text, "
            "and produce concise markdown suitable for a decision log section."
        )

        user_prompt = (
            f"Form: {payload.form}\n"
            f"Ticker: {payload.ticker}\n"
            f"Filing date: {payload.filing_date}\n"
            f"Accession: {payload.accession_number}\n"
            f"Filing URL: {payload.filing_url}\n\n"
            "Instruction file:\n"
            f"{payload.instruction_text}\n\n"
            "Current thesis markdown:\n"
            f"{payload.thesis_text}\n\n"
            "SEC filing excerpt (key sections and exhibits; possibly truncated):\n"
            f"{filing_excerpt}\n\n"
            "Output requirements:\n"
            "1) Return markdown only; no code fences.\n"
            "2) Include a short verdict line with one of: Add, Hold, Trim, Exit, "
            "No Action, Watch, Reduce, Maintain.\n"
            "3) Include evidence references by quoting or citing specific filing details.\n"
            "4) Keep the response between 1 and 4 short paragraphs."
        )

        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise OpenAIEvaluatorError(f"OpenAI evaluation request failed: {exc}") from exc

        text = getattr(response, "output_text", "")
        if not text or not text.strip():
            raise OpenAIEvaluatorError("OpenAI evaluation returned no text.")
        return text.strip()

    def render_status_markdown(
        self,
        *,
        ticker: str,
        filing_form: str,
        filing_date: str,
        accession_number: str,
        evaluation_markdown: str,
        status_instruction_text: str,
        updated_on: str,
        previous_status_markdown: str | None = None,
    ) -> str:
        system_prompt = (
            "You write strict, deterministic markdown status files for investment theses. "
            "Use only the provided evaluation text and instructions."
        )

        user_prompt = (
            f"Ticker: {ticker}\n"
            f"Source filing: {filing_form} ({filing_date}) - {accession_number}\n"
            f"Updated on (today's date): {updated_on}\n\n"
            "Status instructions:\n"
            f"{status_instruction_text}\n\n"
            "Input SEC evaluation markdown (already generated):\n"
            f"{evaluation_markdown}\n\n"
            "Previous status markdown (for continuity, may be empty):\n"
            f"{previous_status_markdown or ''}\n\n"
            "Output requirements:\n"
            "1) Return markdown only; no code fences.\n"
            "2) Return a complete status file document, not a partial patch.\n"
            "3) Use this source accession exactly in marker and metadata.\n"
            "4) Use the given 'Updated on' date exactly.\n"
            "5) Keep claims consistent with the provided SEC evaluation text."
        )

        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise OpenAIEvaluatorError(f"OpenAI status rendering request failed: {exc}") from exc

        text = getattr(response, "output_text", "")
        if not text or not text.strip():
            raise OpenAIEvaluatorError("OpenAI status rendering returned no text.")
        return text.strip()


@dataclass(frozen=True)
class LeverageMetrics:
    total_debt: float | None
    shareholders_equity: float | None
    total_assets: float | None
    net_debt: float | None
    ebitda: float | None
    ebit: float | None
    interest_expense: float | None
    company_name: str | None = None
    period_end: str | None = None
    currency: str | None = None
    fixed_cost_notes: str | None = None
    # Months covered by the EBITDA/EBIT/interest figures (3 for a quarter, 12 for a year).
    flow_period_months: int | None = None


class OpenAILeverageEvaluator:
    """Extracts leverage inputs and generates leverage reports from SEC filings."""

    def __init__(self, model: str | None = None, max_filing_chars: int = 90000):
        self.client = create_openai_client(OpenAILeverageError)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.max_filing_chars = max_filing_chars

    def evaluate(
        self,
        *,
        ticker: str,
        filing: FilingRecord,
        filing_text: str,
        instruction_text: str,
    ) -> tuple[LeverageMetrics, dict[str, float | None], str, str]:
        prepared_filing = self._prepare_filing_text(filing_text, retry_mode=False)
        extraction_raw = self._extract_metrics_json(
            ticker,
            filing,
            prepared_filing,
            retry_note=None,
        )
        metrics = self._parse_metrics(extraction_raw)

        # Some filings place debt and interest details deep in tables/notes.
        # Retry with broader windows if most core fields are missing.
        if self._count_missing_core_metrics(metrics) >= 3:
            retry_excerpt = self._prepare_filing_text(filing_text, retry_mode=True)
            retry_raw = self._extract_metrics_json(
                ticker,
                filing,
                retry_excerpt,
                retry_note=(
                    "Previous extraction missed several core fields. "
                    "Re-check balance sheet, debt footnotes, and income statement sections."
                ),
            )
            retry_metrics = self._parse_metrics(retry_raw)
            if self._count_missing_core_metrics(retry_metrics) < self._count_missing_core_metrics(metrics):
                extraction_raw = retry_raw
                metrics = retry_metrics

        calculated = self._calculate_ratios(metrics, form=filing.form)
        report = self._generate_report(
            ticker=ticker,
            filing=filing,
            instruction_text=instruction_text,
            metrics=metrics,
            calculated=calculated,
            extraction_raw=extraction_raw,
        )
        return metrics, calculated, report, extraction_raw

    def _extract_metrics_json(
        self,
        ticker: str,
        filing: FilingRecord,
        filing_excerpt: str,
        retry_note: str | None,
    ) -> str:
        system_prompt = (
            "You are a forensic financial analyst. Extract leverage-relevant numeric inputs "
            "from SEC filings with high precision. Return strict JSON only."
        )

        user_prompt = (
            f"Ticker: {ticker}\n"
            f"Filing form: {filing.form}\n"
            f"Filing date: {filing.filing_date}\n"
            f"Accession: {filing.accession_number}\n"
            f"Filing URL: {filing.primary_document_url}\n\n"
            "Task:\n"
            "Extract financial values needed for leverage calculations from this filing. "
            "Prefer the latest period shown in the filing statements.\n\n"
            "If debt is split across current and long-term portions, combine them for total_debt.\n"
            "If net debt is not explicit, infer as total debt minus cash and equivalents when available; otherwise null.\n"
            "For EBITDA, use reported EBITDA if present; otherwise keep null (do not fabricate).\n"
            "Interest expense should be the financing cost line item for the latest comparable period, "
            "reported as a positive number.\n"
            "Set flow_period_months to the number of months covered by the EBITDA, EBIT and interest "
            "expense values (3 for a single quarter, 6 or 9 for year-to-date, 12 for a full year).\n\n"
            "Return ONLY valid JSON with this schema:\n"
            "{\n"
            '  "company_name": string|null,\n'
            '  "period_end": string|null,\n'
            '  "currency": string|null,\n'
            '  "flow_period_months": number|null,\n'
            '  "values": {\n'
            '    "total_debt": number|null,\n'
            '    "shareholders_equity": number|null,\n'
            '    "total_assets": number|null,\n'
            '    "net_debt": number|null,\n'
            '    "ebitda": number|null,\n'
            '    "ebit": number|null,\n'
            '    "interest_expense": number|null\n'
            "  },\n"
            '  "fixed_cost_notes": string|null,\n'
            '  "notes": string|null,\n'
            '  "citations": [string]\n'
            "}\n\n"
            "Rules:\n"
            "1) Numbers must be plain numeric values (no commas, no currency symbols).\n"
            "2) If a value is not available, set it to null.\n"
            "3) citations should include short references (e.g., statement names or sections).\n"
            "4) Do not include markdown, code fences, or commentary outside JSON.\n\n"
            f"Retry guidance: {retry_note or 'N/A'}\n\n"
            "SEC filing excerpt:\n"
            f"{filing_excerpt}"
        )

        # Values must come from the filing itself, so web search is disabled here.
        return create_response_text(
            self.client,
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            error_type=OpenAILeverageError,
            web_search=False,
        )

    def _generate_report(
        self,
        *,
        ticker: str,
        filing: FilingRecord,
        instruction_text: str,
        metrics: LeverageMetrics,
        calculated: dict[str, float | None],
        extraction_raw: str,
    ) -> str:
        system_prompt = (
            "You are an investment risk analyst specializing in leverage diagnostics. "
            "Produce concise, factual markdown."
        )
        category = leverage_category(calculated)

        user_prompt = (
            f"Ticker: {ticker}\n"
            f"Filing form: {filing.form}\n"
            f"Filing date: {filing.filing_date}\n"
            f"Accession: {filing.accession_number}\n"
            f"Filing URL: {filing.primary_document_url}\n\n"
            "Instruction framework:\n"
            f"{instruction_text}\n\n"
            "Extracted values (from filing extraction):\n"
            f"{json.dumps(_metrics_to_dict(metrics), indent=2)}\n\n"
            "Calculated leverage ratios (Net Debt / EBITDA uses annualized EBITDA):\n"
            f"{json.dumps(calculated, indent=2)}\n\n"
            f"Rule-based leverage category from these ratios: {category}\n\n"
            "Raw extraction JSON:\n"
            f"{extraction_raw}\n\n"
            "Output requirements:\n"
            "1) Return markdown only (no code fences).\n"
            "2) Include sections matching the leverage framework (company-level, investment leverage, "
            "operating vs financial leverage, portfolio perspective, practical interpretation, limitations).\n"
            "3) Reference the key numeric values and calculated ratios in the narrative.\n"
            "4) End with a final line formatted exactly as 'Verdict: <Low|Moderate|High> - <short reason>'. "
            "Use the rule-based category unless the extracted data clearly shows it is misleading; if you "
            "deviate (or it is Unknown), state why in one sentence.\n"
            "5) Keep report practical and concise (roughly 6-12 short paragraphs)."
        )

        return create_response_text(
            self.client,
            model=self.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            error_type=OpenAILeverageError,
            web_search=True,
        )

    def _parse_metrics(self, extraction_raw: str) -> LeverageMetrics:
        parsed_json = _extract_json_object(extraction_raw)

        try:
            payload = json.loads(parsed_json)
        except json.JSONDecodeError as exc:
            raise OpenAILeverageError(
                f"Could not parse extraction JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            payload = {}

        values = payload.get("values", {})
        if not isinstance(values, dict):
            values = {}

        total_debt = _extract_numeric(payload, values, "total_debt", "debt", "gross_debt")
        shareholders_equity = _extract_numeric(
            payload,
            values,
            "shareholders_equity",
            "stockholders_equity",
            "total_equity",
            "equity",
        )
        total_assets = _extract_numeric(payload, values, "total_assets", "assets")
        ebitda = _extract_numeric(payload, values, "ebitda")
        ebit = _extract_numeric(payload, values, "ebit", "operating_income", "income_from_operations")
        interest_expense = _extract_numeric(
            payload,
            values,
            "interest_expense",
            "interest_and_debt_expense",
            "interest_cost",
        )

        net_debt = _extract_numeric(payload, values, "net_debt")
        if net_debt is None:
            cash_equivalents = _extract_numeric(
                payload,
                values,
                "cash_and_cash_equivalents",
                "cash_equivalents",
                "cash",
            )
            if total_debt is not None and cash_equivalents is not None:
                net_debt = total_debt - cash_equivalents

        months = _extract_numeric(payload, values, "flow_period_months", "period_months")
        flow_period_months = int(round(months)) if months is not None and 1 <= months <= 12 else None

        return LeverageMetrics(
            total_debt=total_debt,
            shareholders_equity=shareholders_equity,
            total_assets=total_assets,
            net_debt=net_debt,
            ebitda=ebitda,
            ebit=ebit,
            interest_expense=interest_expense,
            company_name=_extract_text(payload, values, "company_name", "company", "issuer_name"),
            period_end=_extract_text(payload, values, "period_end", "period", "fiscal_period_end"),
            currency=_extract_text(payload, values, "currency", "reporting_currency"),
            fixed_cost_notes=_extract_text(
                payload,
                values,
                "fixed_cost_notes",
                "operating_leverage_notes",
                "notes",
            ),
            flow_period_months=flow_period_months,
        )

    def _calculate_ratios(
        self,
        metrics: LeverageMetrics,
        *,
        form: str,
    ) -> dict[str, float | None]:
        return calculate_leverage_ratios(metrics, form=form)

    def _prepare_filing_text(self, filing_text: str, *, retry_mode: bool = False) -> str:
        # Line-preserving plain text (no XBRL header, decoded entities) so statement labels survive.
        lines = html_to_text(filing_text).splitlines()
        if not lines:
            normalized = re.sub(r"\s+", " ", filing_text).strip()
            return normalized[: self.max_filing_chars]

        core_keywords = [
            "consolidated balance sheet",
            "consolidated statements of financial position",
            "consolidated statements of operations",
            "income statement",
            "interest expense",
            "long-term debt",
            "short-term debt",
            "current portion of long-term debt",
            "total debt",
            "total liabilities",
            "stockholders' equity",
            "shareholders' equity",
            "total assets",
            "ebitda",
            "ebit",
            "operating income",
            "cash and cash equivalents",
            "debt covenant",
            "liquidity and capital resources",
        ]
        retry_keywords = [
            "notes to consolidated financial statements",
            "borrowings",
            "credit facility",
            "senior notes",
            "financing",
            "debt maturities",
            "interest and debt expense",
        ]

        keywords = core_keywords + (retry_keywords if retry_mode else [])
        window = 30 if retry_mode else 18
        keyword_windows = self._collect_keyword_windows(lines, keywords, window=window)

        start_lines = lines[: (260 if retry_mode else 180)]
        end_lines = lines[-(220 if retry_mode else 140) :]

        sections = [
            "[START OF FILING SNIPPET]",
            "\n".join(start_lines),
            "[FINANCIAL KEYWORD WINDOWS]",
            keyword_windows,
            "[END OF FILING SNIPPET]",
            "\n".join(end_lines),
        ]

        combined = "\n\n".join(part for part in sections if part.strip())
        if len(combined) <= self.max_filing_chars:
            return combined
        return combined[: self.max_filing_chars]

    def _collect_keyword_windows(
        self,
        lines: list[str],
        keywords: list[str],
        *,
        window: int,
    ) -> str:
        lowered = [line.lower() for line in lines]
        windows: list[tuple[int, int]] = []

        for idx, line in enumerate(lowered):
            if any(keyword in line for keyword in keywords):
                start = max(0, idx - window)
                end = min(len(lines), idx + window + 1)
                windows.append((start, end))

        if not windows:
            return "\n".join(lines[: min(500, len(lines))])

        merged: list[tuple[int, int]] = []
        for start, end in sorted(windows):
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                prev_start, prev_end = merged[-1]
                merged[-1] = (prev_start, max(prev_end, end))

        chunks: list[str] = []
        for start, end in merged:
            chunks.append("\n".join(lines[start:end]))

        return "\n\n".join(chunks)

    def _count_missing_core_metrics(self, metrics: LeverageMetrics) -> int:
        core_values = (
            metrics.total_debt,
            metrics.shareholders_equity,
            metrics.total_assets,
            metrics.ebit,
            metrics.interest_expense,
        )
        return sum(1 for value in core_values if value is None)


def _extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]

    raise OpenAILeverageError("OpenAI extraction did not return a JSON object.")


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    s = value.strip().lower().replace(",", "")
    s = s.replace("$", "")
    s = s.replace("usd", "").strip()
    if not s:
        return None

    multiplier = 1.0
    if s.endswith("billion"):
        multiplier = 1_000_000_000.0
        s = s[: -len("billion")].strip()
    elif s.endswith("million"):
        multiplier = 1_000_000.0
        s = s[: -len("million")].strip()
    elif s.endswith("thousand"):
        multiplier = 1_000.0
        s = s[: -len("thousand")].strip()

    try:
        return float(s) * multiplier
    except ValueError:
        return None


def _to_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def calculate_leverage_ratios(metrics: LeverageMetrics, *, form: str) -> dict[str, float | None]:
    """Compute leverage ratios, annualizing interim EBITDA and guarding sign issues."""
    months = metrics.flow_period_months or (12 if form.upper().startswith("10-K") else 3)
    annualized_ebitda = (
        metrics.ebitda * 12.0 / months if metrics.ebitda is not None else None
    )

    # Net Debt / EBITDA is meaningless when EBITDA is zero or negative.
    net_debt_to_ebitda = (
        _safe_div(metrics.net_debt, annualized_ebitda)
        if annualized_ebitda is not None and annualized_ebitda > 0
        else None
    )
    # Filings and extractions differ on the sign of interest expense; coverage uses its size.
    interest_expense = abs(metrics.interest_expense) if metrics.interest_expense is not None else None

    return {
        "debt_to_equity": _safe_div(metrics.total_debt, metrics.shareholders_equity),
        "debt_to_assets": _safe_div(metrics.total_debt, metrics.total_assets),
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "interest_coverage": _safe_div(metrics.ebit, interest_expense),
        "ebitda_annualized": annualized_ebitda,
        "flow_period_months": float(months),
    }


def leverage_category(calculated: dict[str, float | None]) -> str:
    """Classify leverage from the available ratios (High wins; Low needs every available ratio low)."""
    nd_to_ebitda = calculated.get("net_debt_to_ebitda")
    coverage = calculated.get("interest_coverage")
    if nd_to_ebitda is None and coverage is None:
        return "Unknown"

    if (nd_to_ebitda is not None and nd_to_ebitda > HIGH_NET_DEBT_TO_EBITDA) or (
        coverage is not None and coverage < HIGH_RISK_INTEREST_COVERAGE
    ):
        return "High"

    low_by_nd = nd_to_ebitda is None or nd_to_ebitda < LOW_NET_DEBT_TO_EBITDA
    low_by_ic = coverage is None or coverage > LOW_RISK_INTEREST_COVERAGE
    if low_by_nd and low_by_ic:
        return "Low"

    return "Moderate"


def _normalize_metric_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _extract_numeric(payload: dict[str, object], values: dict[str, object], *aliases: str) -> float | None:
    normalized_aliases = {_normalize_metric_key(alias) for alias in aliases}

    for source in (values, payload):
        for key, raw_value in source.items():
            if _normalize_metric_key(str(key)) in normalized_aliases:
                parsed = _to_float(raw_value)
                if parsed is not None:
                    return parsed
    return None


def _extract_text(payload: dict[str, object], values: dict[str, object], *aliases: str) -> str | None:
    normalized_aliases = {_normalize_metric_key(alias) for alias in aliases}

    for source in (values, payload):
        for key, raw_value in source.items():
            if _normalize_metric_key(str(key)) in normalized_aliases:
                parsed = _to_text(raw_value)
                if parsed is not None:
                    return parsed
    return None


def _metrics_to_dict(metrics: LeverageMetrics) -> dict[str, object]:
    return {
        "company_name": metrics.company_name,
        "period_end": metrics.period_end,
        "currency": metrics.currency,
        "flow_period_months": metrics.flow_period_months,
        "values": {
            "total_debt": metrics.total_debt,
            "shareholders_equity": metrics.shareholders_equity,
            "total_assets": metrics.total_assets,
            "net_debt": metrics.net_debt,
            "ebitda": metrics.ebitda,
            "ebit": metrics.ebit,
            "interest_expense": metrics.interest_expense,
        },
        "fixed_cost_notes": metrics.fixed_cost_notes,
    }