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


def _ttm_company_facts():
    def flow(concept, rows):
        return {concept: usd(*[fact(v, accn=a, end=e, start=s) for s, e, a, v in rows])}

    return {
        "facts": {
            "us-gaap": {
                **flow(
                    "NetCashProvidedByUsedInOperatingActivities",
                    [
                        ("2025-01-01", "2025-12-31", OTHER, 140_000_000_000),
                        ("2026-01-01", END, ACC, 70_000_000_000),
                        ("2025-01-01", "2025-06-30", ACC, 60_000_000_000),
                        ("2026-04-01", END, ACC, 40_000_000_000),
                    ],
                ),
                **flow(
                    "PaymentsToAcquirePropertyPlantAndEquipment",
                    [
                        ("2025-01-01", "2025-12-31", OTHER, 130_000_000_000),
                        ("2026-01-01", END, ACC, 100_000_000_000),
                        ("2025-01-01", "2025-06-30", ACC, 50_000_000_000),
                    ],
                ),
                **flow(
                    "InterestExpenseNonoperating",
                    [
                        ("2025-01-01", "2025-12-31", OTHER, -4_000_000_000),
                        ("2026-01-01", END, ACC, -2_000_000_000),
                        ("2025-01-01", "2025-06-30", ACC, -1_500_000_000),
                    ],
                ),
            }
        }
    }


def test_trailing_twelve_months_uses_prior_year_comparatives():
    ttm = x.trailing_twelve_months(_ttm_company_facts(), END)
    assert ttm["period_end"] == END
    assert ttm["operating_cash_flow"] == 150_000.0
    assert ttm["capital_expenditures"] == 180_000.0
    assert ttm["free_cash_flow"] == -30_000.0
    assert ttm["interest_expense"] == 4_500.0
    assert "revenue" not in ttm


def test_trailing_twelve_months_needs_prior_year_period():
    company_facts = _ttm_company_facts()
    gaap = company_facts["facts"]["us-gaap"]
    gaap["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"] = [
        f for f in gaap["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"] if f["start"] != "2025-01-01" or f["end"] != "2025-06-30"
    ]
    assert "operating_cash_flow" not in x.trailing_twelve_months(company_facts, END)


def test_trailing_twelve_months_for_annual_period_is_the_fiscal_year():
    ttm = x.trailing_twelve_months(_ttm_company_facts(), "2025-12-31")
    assert ttm["operating_cash_flow"] == 140_000.0


def test_trailing_twelve_months_without_period_end_is_empty():
    assert x.trailing_twelve_months(_ttm_company_facts(), None) == {}


def test_valuation_net_debt_deducts_marketable_securities():
    facts = x.FilingFacts(
        accession=ACC,
        period_end=END,
        instants={
            "LongTermDebtNoncurrent": 100e6,
            "CashAndCashEquivalentsAtCarryingValue": 30e6,
            "MarketableSecuritiesCurrent": 20e6,
        },
    )
    debt = x.valuation_values(facts, "10-Q")["debt_liquidity"]
    assert debt["marketable_securities"] == 20.0
    assert debt["net_debt"] == 50.0
