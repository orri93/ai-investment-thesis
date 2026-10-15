import io
from email.message import Message
from urllib.error import HTTPError

import pytest

import sec_filings
from conftest import make_filing
from sec_filings import SecEdgarError, SecFilingsClient

INDEX_HTML = """
<table class="tableFile" summary="Document Format Files">
 <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
 <tr><td scope="row">1</td><td scope="row">8-K</td>
     <td scope="row"><a href="/ix?doc=/Archives/edgar/data/1018724/000101872425000034/amzn-20250501.htm">amzn-20250501.htm</a></td>
     <td scope="row">8-K</td><td scope="row">34344</td></tr>
 <tr><td scope="row">2</td><td scope="row">EX-99.1</td>
     <td scope="row"><a href="/Archives/edgar/data/1018724/000101872425000034/ex991.htm">ex991.htm</a></td>
     <td scope="row">EX-99.1</td><td scope="row">573817</td></tr>
 <tr><td scope="row">7</td><td scope="row"></td>
     <td scope="row"><a href="/Archives/edgar/data/1018724/000101872425000034/logo.jpg">logo.jpg</a></td>
     <td scope="row">GRAPHIC</td><td scope="row">111415</td></tr>
</table>
<table class="tableFile" summary="Data Files"><tr><td>4</td><td>XSD</td><td><a href="/x.xsd">x.xsd</a></td><td>EX-101.SCH</td></tr></table>
"""


class FakeResponse(io.BytesIO):
    headers = Message()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return HTTPError("https://www.sec.gov/x", code, "error", headers, None)


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(sec_filings.time, "sleep", sleeps.append)
    return sleeps


def test_parse_filing_index_lists_documents_with_types():
    filing = make_filing(form="8-K", accession="0001018724-25-000034")
    attachments = sec_filings._parse_filing_index(INDEX_HTML, filing)
    assert [(a.document_type, a.file_name) for a in attachments] == [
        ("8-K", "amzn-20250501.htm"),
        ("EX-99.1", "ex991.htm"),
        ("GRAPHIC", "logo.jpg"),
    ]
    assert attachments[1].url == f"{filing.archive_folder_url}ex991.htm"


def test_get_bytes_retries_transient_errors(monkeypatch, no_sleep):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise _http_error(503)
        return FakeResponse(b"payload")

    monkeypatch.setattr(sec_filings, "urlopen", fake_urlopen)
    content, _ = SecFilingsClient()._get_bytes("https://www.sec.gov/x")
    assert content == b"payload"
    assert len(calls) == 2
    assert sec_filings.RETRY_BACKOFF_SECONDS in no_sleep


def test_get_bytes_honours_retry_after(monkeypatch, no_sleep):
    responses = [_http_error(429, retry_after="7"), FakeResponse(b"ok")]

    def fake_urlopen(request, timeout):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(sec_filings, "urlopen", fake_urlopen)
    SecFilingsClient()._get_bytes("https://www.sec.gov/x")
    assert 7.0 in no_sleep


def test_get_bytes_does_not_retry_client_errors(monkeypatch, no_sleep):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        raise _http_error(404)

    monkeypatch.setattr(sec_filings, "urlopen", fake_urlopen)
    with pytest.raises(SecEdgarError, match="404"):
        SecFilingsClient()._get_bytes("https://www.sec.gov/x")
    assert len(calls) == 1


def test_get_bytes_gives_up_after_max_attempts(monkeypatch, no_sleep):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        raise _http_error(503)

    monkeypatch.setattr(sec_filings, "urlopen", fake_urlopen)
    with pytest.raises(SecEdgarError, match="503"):
        SecFilingsClient()._get_bytes("https://www.sec.gov/x")
    assert len(calls) == sec_filings.MAX_REQUEST_ATTEMPTS


def test_throttle_waits_between_requests(monkeypatch, no_sleep):
    monkeypatch.setattr(SecFilingsClient, "_last_request_at", sec_filings.time.monotonic())
    SecFilingsClient._throttle()
    assert no_sleep and 0 < no_sleep[0] <= sec_filings.MIN_REQUEST_INTERVAL_SECONDS


def _client_with_submissions() -> tuple[SecFilingsClient, list[str]]:
    client = SecFilingsClient()
    client._company_cache = {
        "AMZN": sec_filings.CompanyInfo(cik="0001018724", ticker="AMZN", title="Amazon")
    }
    client._submissions_cache["0001018724"] = {
        "filings": {
            "recent": {
                "form": ["10-Q"],
                "accessionNumber": ["A-1"],
                "primaryDocument": ["a.htm"],
                "filingDate": ["2026-07-31"],
            },
            "files": [{"name": "CIK0001018724-submissions-001.json"}],
        }
    }
    fetched: list[str] = []

    def fake_get_json(url):
        fetched.append(url)
        return {
            "form": ["10-K"],
            "accessionNumber": ["B-1"],
            "primaryDocument": ["b.htm"],
            "filingDate": ["2010-02-01"],
        }

    client._get_json = fake_get_json
    return client, fetched


def test_historical_submission_pages_are_cached():
    client, fetched = _client_with_submissions()
    first = [f.accession_number for f in client.iter_filings("AMZN")]
    second = [f.accession_number for f in client.iter_filings("AMZN")]
    assert first == second == ["A-1", "B-1"]
    assert len(fetched) == 1


def test_fetch_document_downloads_primary_document_directly():
    client = SecFilingsClient()
    requested = []
    client._get_bytes = lambda url, **kw: (requested.append(url) or (b"<html/>", {"Content-Type": "text/html"}))
    filing = make_filing()
    document = client.fetch_document(filing)
    assert requested == [filing.primary_document_url]
    assert document.text == "<html/>"
