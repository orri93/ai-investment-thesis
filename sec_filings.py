from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPPORTED_FORMS = ("10-K", "10-Q", "8-K")


class SecEdgarError(Exception):
    """Base exception for SEC EDGAR client errors."""


class UserAgentRequiredError(SecEdgarError):
    """Raised when no SEC-compliant user agent is configured."""


class TickerNotFoundError(SecEdgarError):
    """Raised when a ticker cannot be resolved to a SEC company record."""


class FilingNotFoundError(SecEdgarError):
    """Raised when no filing matches the provided filters."""


@dataclass(frozen=True)
class CompanyInfo:
    cik: str
    ticker: str
    title: str


@dataclass(frozen=True)
class FilingRecord:
    cik: str
    ticker: str
    company_name: str
    form: str
    filing_date: str
    accession_number: str
    primary_document: str
    primary_doc_description: str | None = None
    acceptance_datetime: str | None = None
    report_date: str | None = None

    @property
    def accession_number_no_dashes(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def archive_folder_url(self) -> str:
        return (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{int(self.cik)}/{self.accession_number_no_dashes}/"
        )

    @property
    def primary_document_url(self) -> str:
        return f"{self.archive_folder_url}{self.primary_document}"


@dataclass(frozen=True)
class FilingDocument:
    filing: FilingRecord
    content: bytes
    content_type: str | None = None
    encoding: str = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")


class SecFilingsClient:
    """Lookup and download SEC EDGAR filings by ticker.

    SEC asks automated clients to identify themselves with a descriptive
    User-Agent that includes contact information. Pass that explicitly or set
    the SEC_USER_AGENT environment variable.
    """

    ticker_lookup_url = "https://www.sec.gov/files/company_tickers.json"
    submissions_url_template = "https://data.sec.gov/submissions/CIK{cik}.json"
    historical_submissions_url_template = "https://data.sec.gov/submissions/{name}"

    def __init__(self, user_agent: str | None = None, timeout: float = 30.0):
        resolved_user_agent = user_agent or os.getenv("SEC_USER_AGENT")
        if not resolved_user_agent:
            raise UserAgentRequiredError(
                "Set SEC_USER_AGENT or pass user_agent= with an identifier such as "
                "'ai-investment-thesis/1.0 your-email@example.com'."
            )

        self.user_agent = resolved_user_agent
        self.timeout = timeout
        self._company_cache: dict[str, CompanyInfo] | None = None
        self._submissions_cache: dict[str, dict[str, Any]] = {}

    def lookup_company(self, ticker: str) -> CompanyInfo:
        normalized_ticker = ticker.strip().upper()
        companies = self._load_company_cache()

        try:
            return companies[normalized_ticker]
        except KeyError as exc:
            raise TickerNotFoundError(f"Unknown ticker: {ticker}") from exc

    def get_company_submissions(self, ticker: str) -> dict[str, Any]:
        company = self.lookup_company(ticker)
        if company.cik not in self._submissions_cache:
            url = self.submissions_url_template.format(cik=company.cik)
            self._submissions_cache[company.cik] = self._get_json(url)
        return self._submissions_cache[company.cik]

    def list_filings(
        self,
        ticker: str,
        forms: Sequence[str] | None = None,
        *,
        include_amendments: bool = False,
        limit: int = 10,
    ) -> list[FilingRecord]:
        filings: list[FilingRecord] = []
        for filing in self.iter_filings(
            ticker,
            forms=forms,
            include_amendments=include_amendments,
        ):
            filings.append(filing)
            if len(filings) >= limit:
                break
        return filings

    def is_filing_available(
        self,
        ticker: str,
        form: str,
        *,
        include_amendments: bool = False,
    ) -> bool:
        for _ in self.iter_filings(
            ticker,
            forms=(form,),
            include_amendments=include_amendments,
        ):
            return True
        return False

    def iter_filings(
        self,
        ticker: str,
        forms: Sequence[str] | None = None,
        *,
        include_amendments: bool = False,
    ) -> Iterator[FilingRecord]:
        company = self.lookup_company(ticker)
        submissions = self.get_company_submissions(company.ticker)
        allowed_forms = self._normalize_forms(forms, include_amendments)
        seen_accessions: set[str] = set()

        recent_table = submissions.get("filings", {}).get("recent", {})
        for filing in self._records_from_table(company, recent_table):
            if allowed_forms and filing.form not in allowed_forms:
                continue
            seen_accessions.add(filing.accession_number)
            yield filing

        for file_entry in submissions.get("filings", {}).get("files", []):
            file_name = file_entry.get("name")
            if not file_name:
                continue
            historical_filings = self._get_json(
                self.historical_submissions_url_template.format(name=file_name)
            )
            for filing in self._records_from_table(company, historical_filings):
                if filing.accession_number in seen_accessions:
                    continue
                if allowed_forms and filing.form not in allowed_forms:
                    continue
                seen_accessions.add(filing.accession_number)
                yield filing

    def find_filing(
        self,
        ticker: str,
        *,
        form: str | None = None,
        accession_number: str | None = None,
        filing_date: str | None = None,
        include_amendments: bool = False,
    ) -> FilingRecord:
        if not form and not accession_number:
            raise ValueError("Provide form= or accession_number= to locate a filing.")

        forms = (form,) if form else None
        for filing in self.iter_filings(
            ticker,
            forms=forms,
            include_amendments=include_amendments,
        ):
            if accession_number and filing.accession_number != accession_number:
                continue
            if filing_date and filing.filing_date != filing_date:
                continue
            return filing

        filters: list[str] = []
        if form:
            filters.append(f"form={form}")
        if accession_number:
            filters.append(f"accession_number={accession_number}")
        if filing_date:
            filters.append(f"filing_date={filing_date}")
        raise FilingNotFoundError(
            f"No filing found for ticker={ticker} with {', '.join(filters)}"
        )

    def fetch_filing(
        self,
        ticker: str,
        *,
        form: str | None = None,
        accession_number: str | None = None,
        filing_date: str | None = None,
        include_amendments: bool = False,
        encoding: str = "utf-8",
    ) -> FilingDocument:
        filing = self.find_filing(
            ticker,
            form=form,
            accession_number=accession_number,
            filing_date=filing_date,
            include_amendments=include_amendments,
        )
        content, headers = self._get_bytes(filing.primary_document_url)
        return FilingDocument(
            filing=filing,
            content=content,
            content_type=headers.get("Content-Type"),
            encoding=encoding,
        )

    def download_filing(
        self,
        ticker: str,
        destination: str | Path,
        *,
        form: str | None = None,
        accession_number: str | None = None,
        filing_date: str | None = None,
        include_amendments: bool = False,
    ) -> Path:
        document = self.fetch_filing(
            ticker,
            form=form,
            accession_number=accession_number,
            filing_date=filing_date,
            include_amendments=include_amendments,
        )
        output_path = Path(destination)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(document.content)
        return output_path

    def _load_company_cache(self) -> dict[str, CompanyInfo]:
        if self._company_cache is not None:
            return self._company_cache

        payload = self._get_json(self.ticker_lookup_url)
        companies: dict[str, CompanyInfo] = {}

        if isinstance(payload, Mapping):
            values: Iterable[Any] = payload.values()
        else:
            values = payload

        for entry in values:
            cik_value = str(entry["cik_str"])
            ticker = str(entry["ticker"]).upper()
            companies[ticker] = CompanyInfo(
                cik=cik_value.zfill(10),
                ticker=ticker,
                title=str(entry["title"]),
            )

        self._company_cache = companies
        return companies

    def _records_from_table(
        self,
        company: CompanyInfo,
        table: Mapping[str, Sequence[Any]],
    ) -> Iterator[FilingRecord]:
        forms = table.get("form", [])
        for index, form in enumerate(forms):
            accession_number = self._value_at(table.get("accessionNumber", []), index)
            primary_document = self._value_at(table.get("primaryDocument", []), index)
            filing_date = self._value_at(table.get("filingDate", []), index)
            if not accession_number or not primary_document or not filing_date:
                continue

            yield FilingRecord(
                cik=company.cik,
                ticker=company.ticker,
                company_name=company.title,
                form=str(form),
                filing_date=str(filing_date),
                accession_number=str(accession_number),
                primary_document=str(primary_document),
                primary_doc_description=self._optional_value_at(
                    table.get("primaryDocDescription", []), index
                ),
                acceptance_datetime=self._optional_value_at(
                    table.get("acceptanceDateTime", []), index
                ),
                report_date=self._optional_value_at(table.get("reportDate", []), index),
            )

    def _get_json(self, url: str) -> dict[str, Any]:
        content, _ = self._get_bytes(url, accept="application/json")
        return json.loads(content.decode("utf-8"))

    def _get_bytes(
        self,
        url: str,
        *,
        accept: str = "*/*",
    ) -> tuple[bytes, Mapping[str, str]]:
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": accept,
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read(), dict(response.headers.items())
        except HTTPError as exc:
            raise SecEdgarError(f"SEC request failed for {url}: {exc.code}") from exc
        except URLError as exc:
            raise SecEdgarError(f"SEC request failed for {url}: {exc.reason}") from exc

    @staticmethod
    def _normalize_forms(
        forms: Sequence[str] | None,
        include_amendments: bool,
    ) -> set[str] | None:
        if not forms:
            return None

        normalized = {form.strip().upper() for form in forms}
        if include_amendments:
            normalized.update({f"{form}/A" for form in list(normalized)})
        return normalized

    @staticmethod
    def _value_at(values: Sequence[Any], index: int) -> Any:
        if index >= len(values):
            return None
        return values[index]

    @classmethod
    def _optional_value_at(cls, values: Sequence[Any], index: int) -> str | None:
        value = cls._value_at(values, index)
        if value in (None, ""):
            return None
        return str(value)


def list_available_filings(
    ticker: str,
    forms: Sequence[str] | None = SUPPORTED_FORMS,
    *,
    include_amendments: bool = False,
    limit: int = 10,
    user_agent: str | None = None,
) -> list[FilingRecord]:
    client = SecFilingsClient(user_agent=user_agent)
    return client.list_filings(
        ticker,
        forms=forms,
        include_amendments=include_amendments,
        limit=limit,
    )


def filing_available(
    ticker: str,
    form: str,
    *,
    include_amendments: bool = False,
    user_agent: str | None = None,
) -> bool:
    client = SecFilingsClient(user_agent=user_agent)
    return client.is_filing_available(
        ticker,
        form,
        include_amendments=include_amendments,
    )


def fetch_latest_filing(
    ticker: str,
    form: str,
    *,
    include_amendments: bool = False,
    user_agent: str | None = None,
) -> FilingDocument:
    client = SecFilingsClient(user_agent=user_agent)
    return client.fetch_filing(
        ticker,
        form=form,
        include_amendments=include_amendments,
    )