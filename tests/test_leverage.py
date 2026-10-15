from conftest import make_filing
from openai_evaluator import (
    SOURCE_AI,
    SOURCE_XBRL,
    LeverageMetrics,
    _to_float,
    calculate_leverage_ratios,
    leverage_category,
    merge_xbrl_metrics,
)


def metrics(**overrides):
    values = dict(
        total_debt=100.0,
        shareholders_equity=400.0,
        total_assets=900.0,
        net_debt=50.0,
        ebitda=None,
        ebit=None,
        interest_expense=None,
    )
    values.update(overrides)
    return LeverageMetrics(**values)


def test_negative_ebitda_is_not_rated_low():
    ratios = calculate_leverage_ratios(metrics(ebitda=-10.0, ebit=-20.0, interest_expense=5.0), form="10-K")
    assert ratios["net_debt_to_ebitda"] is None
    assert leverage_category(ratios) == "High"


def test_interest_expense_sign_is_ignored():
    ratios = calculate_leverage_ratios(metrics(ebit=100.0, interest_expense=-5.0), form="10-K")
    assert ratios["interest_coverage"] == 20.0


def test_quarterly_ebitda_is_annualized():
    assert calculate_leverage_ratios(metrics(ebitda=10.0), form="10-Q")["ebitda_annualized"] == 40.0
    ytd = calculate_leverage_ratios(metrics(ebitda=30.0, flow_period_months=6), form="10-Q")
    assert ytd["ebitda_annualized"] == 60.0


def test_leverage_category_uses_available_ratios():
    assert leverage_category({"net_debt_to_ebitda": None, "interest_coverage": 20.9}) == "Low"
    assert leverage_category({"net_debt_to_ebitda": 2.0, "interest_coverage": 20.0}) == "Moderate"
    assert leverage_category({"net_debt_to_ebitda": 4.0, "interest_coverage": 20.0}) == "High"
    assert leverage_category({"net_debt_to_ebitda": None, "interest_coverage": None}) == "Unknown"


def test_merge_prefers_xbrl_and_fills_gaps_from_ai():
    ai = metrics(total_debt=1.0, total_assets=None, ebit=5.0, interest_expense=1.0, flow_period_months=3)
    merged = merge_xbrl_metrics(ai, {"total_debt": 2.0, "total_assets": 9.0, "ebit": 6.0, "flow_period_months": 3})
    assert merged.total_debt == 2.0 and merged.total_assets == 9.0 and merged.ebit == 6.0
    assert merged.shareholders_equity == 400.0 and merged.interest_expense == 1.0
    assert merged.value_sources["total_debt"] == SOURCE_XBRL
    assert merged.value_sources["shareholders_equity"] == SOURCE_AI


def test_merge_drops_ai_flows_from_a_different_period():
    ai = metrics(interest_expense=4.0, flow_period_months=6)
    merged = merge_xbrl_metrics(ai, {"ebit": 6.0, "flow_period_months": 3})
    assert merged.interest_expense is None
    assert merged.flow_period_months == 3


def test_merge_without_xbrl_marks_ai_sources():
    merged = merge_xbrl_metrics(metrics(), None)
    assert merged.value_sources == {name: SOURCE_AI for name in ("total_debt", "shareholders_equity", "total_assets", "net_debt")}


def test_to_float_parses_model_number_formats():
    assert _to_float("$1.5 billion") == 1_500_000_000
    assert _to_float("1,234") == 1234
    assert _to_float("n/a") is None


LEVERAGE_LOG = """# AMZN

## Leverage Evaluation Log

### Leverage Review: 10-Q (2026-07-31) - 0001018724-26-000026
<!-- processed-leverage-filing:0001018724-26-000026 -->

#### Calculated Leverage Ratios

| Ratio | Value |
|---|---|
| Debt-to-Equity | 0.24x |
| Net Debt / EBITDA | N/A |
| Interest Coverage (EBIT / Interest Expense) | 20.90x |

#### Leverage Evaluation Report

Debt is modest.

| Debt-to-Equity | 9.99x |

Verdict: Low - modest debt

#### Extraction JSON

```json
{}
```
"""


def test_logged_leverage_entry_reads_ratio_table_and_report(leverage_module):
    calculated, report = leverage_module._logged_leverage_entry(LEVERAGE_LOG, "0001018724-26-000026")
    assert calculated["debt_to_equity"] == 0.24
    assert calculated["interest_coverage"] == 20.9
    assert calculated["net_debt_to_ebitda"] is None
    assert report.startswith("Debt is modest.") and "Extraction JSON" not in report


def test_leverage_verdict_comes_from_final_line(leverage_module):
    report = "Verdict style intro mentions verdict: nothing\n\nBody\n\nVerdict: Low - modest debt"
    assert leverage_module._extract_verdict(report) == "Verdict: Low - modest debt"


def test_extracted_values_table_shows_sources(leverage_module):
    merged = merge_xbrl_metrics(metrics(), {"total_debt": 2.0})
    table = leverage_module._format_extracted_values(merged)
    assert "| Metric | Value | Source |" in table
    assert "| Total Debt | 2.00 | SEC XBRL |" in table


def test_restore_leverage_block_from_log(tmp_path, leverage_module):
    status = tmp_path / "amzn.md"
    status.write_text("# AMZN Thesis Status\n\n## Latest assessment\n- Summary.\n", encoding="utf-8")
    filing = make_filing()
    assert leverage_module._restore_leverage_status_if_missing(
        status_path=status, leverage_log_text=LEVERAGE_LOG, filing=filing
    )
    text = status.read_text(encoding="utf-8")
    assert "Debt-to-Equity: 0.24x" in text and "Leverage category: Low" in text
    assert not leverage_module._restore_leverage_status_if_missing(
        status_path=status, leverage_log_text=LEVERAGE_LOG, filing=filing
    )
