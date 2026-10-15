from test_xbrl_facts import ACC, COMPANY_FACTS


def test_qualitative_context_budget_uses_only_included_8ks(valuation_module):
    texts = [{"form": "10-K", "filing_date": "2026-02-01", "text": "K" * 100_000}] + [
        {"form": "8-K", "filing_date": "2026-03-01", "text": "E" * 20_000} for _ in range(50)
    ]
    context = valuation_module._build_qualitative_context(texts, max_chars=45_000)
    parts = [p for p in context.split("\n\n---\n\n") if p.startswith("[8-K")]
    assert len(parts) == valuation_module.MAX_QUALITATIVE_8KS
    assert min(len(p) for p in parts) > 4000


def test_xbrl_values_override_model_extraction(valuation_module):
    extraction = {
        "revenue_margins": {"total_revenue": 1.0, "gross_margin_pct": 50.0},
        "debt_liquidity": "not a dict",
    }
    xbrl = {"revenue_margins": {"total_revenue": 200_606.0}, "debt_liquidity": {"total_debt": 132_549.0}}
    merged = valuation_module.apply_xbrl_overrides(extraction, xbrl)
    assert merged["revenue_margins"] == {"total_revenue": 200_606.0, "gross_margin_pct": 50.0}
    assert merged["debt_liquidity"] == {"total_debt": 132_549.0}
    assert merged["_xbrl_fields"] == ["revenue_margins.total_revenue", "debt_liquidity.total_debt"]


def test_xbrl_valuation_values_for_filing(valuation_module):
    info = {"form": "10-Q", "accession_number": ACC, "report_date": "2026-06-30"}
    values = valuation_module._xbrl_valuation_values(COMPANY_FACTS, info)
    assert values["debt_liquidity"]["total_debt"] == 132_549.0
    assert valuation_module._xbrl_valuation_values(None, info) == {}
