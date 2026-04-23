from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from openai import OpenAI

from sec_filings import FilingRecord


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


class OpenAIThesisEvaluator:
    """Runs form-specific investment thesis evaluations with OpenAI."""

    def __init__(self, model: str | None = None, max_filing_chars: int = 60000):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.max_filing_chars = max_filing_chars

    def evaluate(self, payload: EvaluationInput) -> str:
        filing_excerpt = self._prepare_filing_text(payload.filing_text)

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
            "SEC filing excerpt (possibly truncated):\n"
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

    def _prepare_filing_text(self, filing_text: str) -> str:
        # Filings are often HTML-heavy; normalize whitespace and cap size to stay token-safe.
        without_tags = re.sub(r"<[^>]+>", " ", filing_text)
        normalized = re.sub(r"\s+", " ", without_tags).strip()
        if len(normalized) <= self.max_filing_chars:
            return normalized
        return normalized[: self.max_filing_chars]


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


class OpenAILeverageEvaluator:
    """Extracts leverage inputs and generates leverage reports from SEC filings."""

    def __init__(self, model: str | None = None, max_filing_chars: int = 90000):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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

        calculated = self._calculate_ratios(metrics)
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
            "Interest expense should be the financing cost line item for the latest comparable period.\n\n"
            "Return ONLY valid JSON with this schema:\n"
            "{\n"
            '  "company_name": string|null,\n'
            '  "period_end": string|null,\n'
            '  "currency": string|null,\n'
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

        response = self._create_response_with_optional_web_search(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        text = getattr(response, "output_text", "")
        if not text or not text.strip():
            raise OpenAILeverageError("OpenAI extraction returned no text.")
        return text.strip()

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
            "Calculated leverage ratios:\n"
            f"{json.dumps(calculated, indent=2)}\n\n"
            "Raw extraction JSON:\n"
            f"{extraction_raw}\n\n"
            "Output requirements:\n"
            "1) Return markdown only (no code fences).\n"
            "2) Include sections matching the leverage framework (company-level, investment leverage, "
            "operating vs financial leverage, portfolio perspective, practical interpretation, limitations).\n"
            "3) Reference the key numeric values and calculated ratios in the narrative.\n"
            "4) Add a short final verdict line with leverage category: Low, Moderate, or High.\n"
            "5) Keep report practical and concise (roughly 6-12 short paragraphs)."
        )

        response = self._create_response_with_optional_web_search(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        text = getattr(response, "output_text", "")
        if not text or not text.strip():
            raise OpenAILeverageError("OpenAI report generation returned no text.")
        return text.strip()

    def _create_response_with_optional_web_search(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ):
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "tools": [{"type": "web_search_preview"}],
        }
        try:
            return self.client.responses.create(**payload)
        except Exception:
            payload.pop("tools", None)
            try:
                return self.client.responses.create(**payload)
            except Exception as exc:
                raise OpenAILeverageError(f"OpenAI request failed: {exc}") from exc

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
        )

    def _calculate_ratios(self, metrics: LeverageMetrics) -> dict[str, float | None]:
        debt_to_equity = _safe_div(metrics.total_debt, metrics.shareholders_equity)
        debt_to_assets = _safe_div(metrics.total_debt, metrics.total_assets)
        net_debt_to_ebitda = _safe_div(metrics.net_debt, metrics.ebitda)
        interest_coverage = _safe_div(metrics.ebit, metrics.interest_expense)

        return {
            "debt_to_equity": debt_to_equity,
            "debt_to_assets": debt_to_assets,
            "net_debt_to_ebitda": net_debt_to_ebitda,
            "interest_coverage": interest_coverage,
        }

    def _prepare_filing_text(self, filing_text: str, *, retry_mode: bool = False) -> str:
        # Convert filing HTML/text to line-preserving plain text so statement labels survive.
        text = filing_text
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?i)</?(br|p|div|tr|li|h1|h2|h3|h4|h5|h6|table|section)[^>]*>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
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