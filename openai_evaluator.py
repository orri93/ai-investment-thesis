from __future__ import annotations

import os
import re
from dataclasses import dataclass

from openai import OpenAI


class OpenAIEvaluatorError(Exception):
    """Raised when thesis evaluation with OpenAI cannot be completed."""


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