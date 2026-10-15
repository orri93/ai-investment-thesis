import xbrl_facts as x

ACC = "0001018724-26-000026"
OTHER = "0001018724-26-000014"
END = "2026-06-30"
Q2 = ("2026-04-01", END)
H1 = ("2026-01-01", END)


def fact(val, accn=ACC, end=END, start=None):
    data = {"val": val, "accn": accn, "end": end, "form": "10-Q"}
    if start:
        data["start"] = start
    return data


def usd(*facts):
    return {"units": {"USD": list(facts)}}


COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "LongTermDebtNoncurrent": usd(fact(128_894_000_000), fact(65_648_000_000, accn=OTHER, end="2026-03-31")),
            "LongTermDebtCurrent": usd(fact(3_330_000_000)),
            "ShortTermBorrowings": usd(fact(325_000_000)),
            "StockholdersEquity": usd(fact(551_620_000_000)),
            "Assets": usd(fact(1_095_689_000_000)),
            "CashAndCashEquivalentsAtCarryingValue": usd(fact(78_213_000_000)),
            "OperatingIncomeLoss": usd(fact(27_461_000_000, start=Q2[0]), fact(51_313_000_000, start=H1[0])),
            "DepreciationDepletionAndAmortization": usd(
                fact(19_988_000_000, start=Q2[0]), fact(38_933_000_000, start=H1[0])
            ),
            "InterestExpenseNonoperating": usd(fact(-1_314_000_000, start=Q2[0])),
            "RevenueFromContractWithCustomerExcludingAssessedTax": usd(fact(200_606_000_000, start=Q2[0])),
            "NetCashProvidedByUsedInOperatingActivities": usd(fact(45_387_000_000, start=Q2[0])),
            "PaymentsToAcquireProductiveAssets": usd(fact(54_208_000_000, start=Q2[0])),
            "WeightedAverageNumberOfDilutedSharesOutstanding": {
                "units": {"shares": [fact(10_903_000_000, start=Q2[0])]}
            },
        }
    }
}


def test_facts_for_filing_keeps_only_this_filing_and_period():
    facts = x.facts_for_filing(COMPANY_FACTS, ACC, END)
    assert facts.instants["LongTermDebtNoncurrent"] == 128_894_000_000
    assert set(facts.durations) == {Q2, H1}


def test_period_end_is_inferred_when_missing():
    assert x.facts_for_filing(COMPANY_FACTS, ACC, None).period_end == END


def test_unknown_accession_returns_none():
    assert x.facts_for_filing(COMPANY_FACTS, "0000000000-00-000000") is None


def test_total_debt_combines_noncurrent_current_and_short_term():
    facts = x.facts_for_filing(COMPANY_FACTS, ACC, END)
    assert x.total_debt(facts) == 132_549_000_000


def test_total_debt_prefers_debt_current_when_reported():
    facts = x.FilingFacts(
        accession=ACC,
        period_end=END,
        instants={"LongTermDebtNoncurrent": 100.0, "DebtCurrent": 20.0, "ShortTermBorrowings": 5.0},
    )
    assert x.total_debt(facts) == 120.0


def test_flow_period_prefers_quarter_with_depreciation():
    facts = x.facts_for_filing(COMPANY_FACTS, ACC, END)
    assert x.choose_flow_period(facts, "10-Q") == Q2
    assert x.period_months(Q2) == 3


def test_leverage_values():
    values = x.leverage_values(x.facts_for_filing(COMPANY_FACTS, ACC, END), "10-Q")
    assert values["total_debt"] == 132_549_000_000
    assert values["net_debt"] == 132_549_000_000 - 78_213_000_000
    assert values["ebit"] == 27_461_000_000
    assert values["ebitda"] == 27_461_000_000 + 19_988_000_000
    assert values["interest_expense"] == 1_314_000_000
    assert values["flow_period_months"] == 3


def test_valuation_values_are_in_millions_and_drop_missing():
    values = x.non_null_values(x.valuation_values(x.facts_for_filing(COMPANY_FACTS, ACC, END), "10-Q"))
    assert values["revenue_margins"]["total_revenue"] == 200_606.0
    assert values["cash_flow"]["free_cash_flow"] == 45_387.0 - 54_208.0
    assert values["debt_liquidity"]["total_debt"] == 132_549.0
    assert values["capital_allocation"]["shares_outstanding_diluted"] == 10_903.0
    assert "gross_profit" not in values["revenue_margins"]
