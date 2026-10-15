import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sec_filings import FilingRecord  # noqa: E402


def _load_script(module_name: str, file_name: str):
    """Import an entry-point script whose file name contains hyphens."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, ROOT / file_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def leverage_module():
    return _load_script("leverage_evaluator", "leverage-evaluator.py")


@pytest.fixture(scope="session")
def valuation_module():
    return _load_script("valuation_models", "valuation-models.py")


@pytest.fixture(scope="session")
def generator_module():
    return _load_script("thesis_generator", "thesis-generator.py")


@pytest.fixture(autouse=True)
def _sec_user_agent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "ai-investment-thesis-tests test@example.com")


def make_filing(
    form: str = "10-Q",
    filing_date: str = "2026-07-31",
    accession: str = "0001018724-26-000026",
    report_date: str | None = "2026-06-30",
) -> FilingRecord:
    return FilingRecord(
        cik="0001018724",
        ticker="AMZN",
        company_name="Amazon.com, Inc.",
        form=form,
        filing_date=filing_date,
        accession_number=accession,
        primary_document="amzn-20260630.htm",
        report_date=report_date,
    )
