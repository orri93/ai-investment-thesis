from datetime import date

import pytest

import main
import status_file
from conftest import make_filing

FILING_LOG = """# AMZN

## Evaluation Log

### SEC Filing Review: 10-Q (2026-07-31) - 0001018724-26-000026
<!-- processed-sec-filing:0001018724-26-000026 -->
- Filing URL: https://example.test/q
- Processed on: 2026-08-01

**Verdict: Hold** Results support the thesis.

### SEC Filing Review: 8-K (2026-09-09) - 0001018724-26-000036
<!-- processed-sec-filing:0001018724-26-000036 -->
- Filing URL: https://example.test/8k
- Processed on: 2026-09-10

**Verdict: No Action — Informational.** Board appointment.
"""


class FakeSec:
    def __init__(self, filings):
        self.filings = filings
        self.fetched = []

    def iter_filings(self, ticker, forms=None, include_amendments=False):
        for filing in self.filings:
            if forms is None or filing.form in forms:
                yield filing

    def fetch_document(self, filing):
        self.fetched.append(filing.accession_number)
        return type("Doc", (), {"text": "<p>filing text</p>"})()


class FakeEvaluator:
    def __init__(self, evaluation="**Verdict: Watch** Revised view.", status=None):
        self.evaluation = evaluation
        self.status = status
        self.inputs = []
        self.status_calls = []

    def evaluate(self, payload):
        self.inputs.append(payload)
        return self.evaluation

    def render_status_markdown(self, **kwargs):
        self.status_calls.append(kwargs)
        return self.status


@pytest.mark.parametrize(
    "text, expected",
    [
        ("**Verdict: Watch — Material event.**", "Watch"),
        ("**Verdict:** Hold", "Hold"),
        ("**Verdict: No Action — Informational.**", "No Action"),
        ("Verdict line: Exit", "Exit"),
        ("Verdict: unclear", None),
    ],
)
def test_extract_verdict(text, expected):
    assert main._extract_verdict(text) == expected


def test_parse_purchase_date_takes_earliest():
    thesis = "## Position\n- Purchased: Mar 18, 2025\n- Purchased: 2024-11-02\n"
    assert main._parse_purchase_date(thesis) == date(2024, 11, 2)
    assert main._parse_purchase_date("- Purchased: someday") is None


def test_informational_8k_is_not_status_relevant():
    latest = main._latest_relevant_entry(FILING_LOG)
    assert latest["accession"] == "0001018724-26-000026"
    assert latest["key"] == "0001018724-26-000026"


def test_collect_filings_scans_past_limit_to_catch_up():
    filings = [make_filing(filing_date=f"2026-{12 - i:02d}-01", accession=f"A{i}") for i in range(10)]
    sec = FakeSec(filings)
    log = main.PROCESSED_MARKER_TEMPLATE.format(accession="A6")
    scanned = main._collect_filings_to_scan(sec, "AMZN", log_text=log, purchase_date=None, filings_limit=3)
    assert [f.accession_number for f in scanned] == ["A0", "A1", "A2", "A3", "A4", "A5"]
    first_run = main._collect_filings_to_scan(sec, "AMZN", log_text="", purchase_date=None, filings_limit=3)
    assert len(first_run) == 3
    bounded = main._collect_filings_to_scan(
        sec, "AMZN", log_text=log, purchase_date=date(2026, 9, 15), filings_limit=3
    )
    assert [f.accession_number for f in bounded] == ["A0", "A1", "A2"]


def test_thesis_fingerprint_ignores_line_endings_and_trailing_spaces():
    assert main._thesis_fingerprint("a  \r\nb\r\n") == main._thesis_fingerprint("a\nb")
    assert main._thesis_fingerprint("a\nb") != main._thesis_fingerprint("a\nc")


def test_set_thesis_fingerprint_inserts_then_replaces():
    once = main._set_thesis_fingerprint(FILING_LOG, "a" * 64)
    assert once.splitlines()[1] == f"<!-- thesis-sha256:{'a' * 64} -->"
    twice = main._set_thesis_fingerprint(once, "b" * 64)
    assert main._recorded_thesis_fingerprint(twice) == "b" * 64
    assert twice.count("thesis-sha256") == 1


def _review(tmp_path, log_text, *, thesis="revised thesis", periodic=False, evaluator=None):
    log_path = tmp_path / "amzn.md"
    log_path.write_text(log_text, encoding="utf-8")
    sec = FakeSec([make_filing(form="10-Q")])
    evaluator = evaluator or FakeEvaluator()
    new_log, reviewed = main._review_thesis_change(
        ticker="AMZN",
        thesis_text=thesis,
        log_text=log_text,
        log_path=log_path,
        sec_client=sec,
        evaluator=evaluator,
        instruction_texts={"10-Q": "q instructions", "10-K": "k instructions"},
        periodic_reviewed_this_run=periodic,
    )
    return new_log, reviewed, evaluator, log_path


def test_first_fingerprint_is_a_baseline_without_review(tmp_path):
    new_log, reviewed, evaluator, log_path = _review(tmp_path, FILING_LOG)
    assert not reviewed and evaluator.inputs == []
    assert main._recorded_thesis_fingerprint(log_path.read_text(encoding="utf-8")) == main._thesis_fingerprint(
        "revised thesis"
    )


def test_changed_thesis_triggers_revision_review(tmp_path):
    old = main._set_thesis_fingerprint(FILING_LOG, main._thesis_fingerprint("old thesis"))
    new_log, reviewed, evaluator, _ = _review(tmp_path, old)
    assert reviewed
    assert evaluator.inputs[0].review_note == main.REVISION_REVIEW_NOTE
    assert evaluator.inputs[0].thesis_text == "revised thesis"
    assert "### Thesis Revision Review: 10-Q (2026-07-31) - 0001018724-26-000026" in new_log

    latest = main._latest_relevant_entry(new_log)
    fingerprint = main._thesis_fingerprint("revised thesis")[:12]
    assert latest["kind"] == "revision"
    assert latest["key"] == f"0001018724-26-000026+thesis-{fingerprint}"
    assert "Revised view." in latest["evaluation"] and "Thesis fingerprint" not in latest["evaluation"]


def test_unchanged_or_already_reviewed_thesis_makes_no_call(tmp_path):
    current = main._set_thesis_fingerprint(FILING_LOG, main._thesis_fingerprint("revised thesis"))
    _, reviewed, evaluator, _ = _review(tmp_path, current)
    assert not reviewed and evaluator.inputs == []

    old = main._set_thesis_fingerprint(FILING_LOG, main._thesis_fingerprint("old thesis"))
    new_log, reviewed, evaluator, _ = _review(tmp_path, old, periodic=True)
    assert not reviewed and evaluator.inputs == []
    assert main._recorded_thesis_fingerprint(new_log) == main._thesis_fingerprint("revised thesis")


def test_failed_revision_review_keeps_old_fingerprint(tmp_path):
    class FailingEvaluator(FakeEvaluator):
        def evaluate(self, payload):
            raise main.OpenAIEvaluatorError("boom")

    old_fingerprint = main._thesis_fingerprint("old thesis")
    old = main._set_thesis_fingerprint(FILING_LOG, old_fingerprint)
    with pytest.raises(main.OpenAIEvaluatorError):
        _review(tmp_path, old, evaluator=FailingEvaluator())
    assert main._recorded_thesis_fingerprint((tmp_path / "amzn.md").read_text(encoding="utf-8")) == old_fingerprint


LEVERAGE_BLOCK = [status_file.LEVERAGE_STATUS_START_MARKER, "- Leverage category: Low",
                  status_file.LEVERAGE_STATUS_END_MARKER]


def test_status_update_enforces_metadata_and_keeps_leverage_block(tmp_path):
    status_path = tmp_path / "status.md"
    existing = (
        "# AMZN Thesis Status\n\n<!-- status-source-accession:OLD -->\n- Verdict: Hold\n\n"
        "## Latest assessment\n- Old.\n\n" + "\n".join(LEVERAGE_BLOCK) + "\n"
    )
    status_path.write_text(existing, encoding="utf-8")
    model_status = (
        "# AMZN Thesis Status\n\n<!-- status-source-accession:WRONG -->\n"
        "- Updated on: 1999-01-01\n- Verdict: Hold\n\n## Latest assessment\n- New.\n"
    )
    evaluator = FakeEvaluator(status=model_status)

    assert main._update_status_file_if_needed(
        ticker="AMZN",
        log_text=FILING_LOG,
        status_path=status_path,
        evaluator=evaluator,
        status_instruction_text="rules",
    )
    result = status_path.read_text(encoding="utf-8")
    assert main._extract_status_source_accession(result) == "0001018724-26-000026"
    assert "1999-01-01" not in result
    assert status_file.extract_leverage_block(result) == LEVERAGE_BLOCK
    assert status_file.LEVERAGE_STATUS_START_MARKER not in evaluator.status_calls[0]["previous_status_markdown"]

    assert not main._update_status_file_if_needed(
        ticker="AMZN",
        log_text=FILING_LOG,
        status_path=status_path,
        evaluator=evaluator,
        status_instruction_text="rules",
    )
    assert len(evaluator.status_calls) == 1


def test_status_fallback_uses_logged_verdict(tmp_path):
    status_path = tmp_path / "status.md"
    main._update_status_file_if_needed(
        ticker="AMZN",
        log_text=FILING_LOG,
        status_path=status_path,
        evaluator=FakeEvaluator(status="I cannot help with that."),
        status_instruction_text="rules",
    )
    result = status_path.read_text(encoding="utf-8")
    assert "- Verdict: Hold" in result and "- Overall status: Green" in result
    assert "status rendering failed" in result


def test_status_for_revision_review_uses_revision_key(tmp_path):
    old = main._set_thesis_fingerprint(FILING_LOG, main._thesis_fingerprint("old thesis"))
    new_log, _, _, _ = _review(tmp_path, old)
    status_path = tmp_path / "status.md"
    evaluator = FakeEvaluator(status="# AMZN Thesis Status\n- Verdict: Watch\n")
    main._update_status_file_if_needed(
        ticker="AMZN", log_text=new_log, status_path=status_path, evaluator=evaluator, status_instruction_text="r"
    )
    source = main._extract_status_source_accession(status_path.read_text(encoding="utf-8"))
    assert source.startswith("0001018724-26-000026+thesis-")
    assert evaluator.status_calls[0]["filing_form"] == "10-Q (thesis revision review)"
