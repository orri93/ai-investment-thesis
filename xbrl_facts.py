"""As-reported financial values for a single filing from SEC XBRL company facts.

Company facts (data.sec.gov/api/xbrl/companyfacts) list every value a company has
tagged, each with the accession number of the filing that reported it. Selecting
facts by accession and period end gives exact statement values for that filing,
which are more reliable than values a language model reads from filing text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

USD = "USD"
SHARES = "shares"

# Concept aliases in order of preference.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "assets": ("Assets",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "marketable_securities": ("MarketableSecuritiesCurrent",),
    "long_term_debt_total": ("LongTermDebt",),
    "long_term_debt_noncurrent": ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"),
    "long_term_debt_current": ("LongTermDebtCurrent",),
    "debt_current": ("DebtCurrent",),
    "short_term_borrowings": ("ShortTermBorrowings",),
    "commercial_paper": ("CommercialPaper",),
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "interest_expense": ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"),
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "stock_based_compensation": ("ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
    "dividends_paid": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "rd_expense": ("ResearchAndDevelopmentExpense",),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
}
SHARE_CONCEPTS = {"diluted_shares"}

# Flow concepts summed over four quarters for trailing-twelve-month figures.
TTM_KEYS = (
    "revenue",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capital_expenditures",
    "depreciation_amortization",
    "stock_based_compensation",
    "interest_expense",
)


@dataclass(frozen=True)
class FilingFacts:
    """Facts reported in one filing for its own period end."""

    accession: str
    period_end: str
    instants: dict[str, float] = field(default_factory=dict)
    # (start, end) -> {concept: value}
    durations: dict[tuple[str, str], dict[str, float]] = field(default_factory=dict)

    def instant(self, key: str) -> float | None:
        return _first(self.instants, CONCEPTS[key])

    def duration(self, key: str, period: tuple[str, str] | None) -> float | None:
        if period is None:
            return None
        return _first(self.durations.get(period, {}), CONCEPTS[key])

    def periods_for(self, key: str) -> list[tuple[str, str]]:
        """Periods (shortest first) for which any alias of key was reported."""
        aliases = CONCEPTS[key]
        found = [p for p, values in self.durations.items() if any(a in values for a in aliases)]
        return sorted(found, key=_period_days)


def facts_for_filing(
    company_facts: dict[str, Any],
    accession: str,
    period_end: str | None = None,
) -> FilingFacts | None:
    """Collect the us-gaap facts a filing reported for its own period end."""
    gaap = company_facts.get("facts", {}).get("us-gaap", {})
    wanted = {alias for aliases in CONCEPTS.values() for alias in aliases}

    rows: list[tuple[str, dict[str, Any]]] = []
    for concept in wanted:
        units = gaap.get(concept, {}).get("units", {})
        for unit in (USD, SHARES):
            for fact in units.get(unit, []):
                if fact.get("accn") == accession and isinstance(fact.get("val"), (int, float)):
                    rows.append((concept, fact))
    if not rows:
        return None

    if not period_end:
        # The filing's own balance sheet date is the latest instant it reports.
        instant_ends = [fact["end"] for _, fact in rows if "start" not in fact]
        period_end = max(instant_ends or [fact["end"] for _, fact in rows])

    facts = FilingFacts(accession=accession, period_end=period_end)
    for concept, fact in rows:
        if fact.get("end") != period_end:
            continue
        value = float(fact["val"])
        if "start" in fact:
            facts.durations.setdefault((fact["start"], fact["end"]), {})[concept] = value
        else:
            facts.instants[concept] = value
    return facts


def period_months(period: tuple[str, str]) -> int:
    return max(1, round(_period_days(period) / 30.44))


def choose_flow_period(facts: FilingFacts, form: str) -> tuple[str, str] | None:
    """Pick the income-statement period for ratios.

    Annual reports use the 12-month period; quarterly reports prefer the shortest
    period that also reports depreciation & amortization, so EBITDA can be computed
    from one consistent period.
    """
    periods = facts.periods_for("operating_income")
    if not periods:
        return None
    if form.upper().startswith("10-K"):
        annual = [p for p in periods if period_months(p) == 12]
        return annual[0] if annual else periods[-1]
    for period in periods:
        if facts.duration("depreciation_amortization", period) is not None:
            return period
    return periods[0]


def total_debt(facts: FilingFacts) -> float | None:
    """Total borrowings: long-term debt (current + noncurrent) plus short-term debt."""
    short_term = _sum(facts.instant("short_term_borrowings"), facts.instant("commercial_paper"))
    debt_current = facts.instant("debt_current")
    noncurrent = facts.instant("long_term_debt_noncurrent")
    if noncurrent is not None:
        current = debt_current if debt_current is not None else _sum(
            facts.instant("long_term_debt_current"), short_term
        )
        return noncurrent + (current or 0.0)

    long_term_total = facts.instant("long_term_debt_total")
    if long_term_total is not None:
        return long_term_total + (short_term or 0.0)
    return debt_current


def leverage_values(facts: FilingFacts, form: str) -> dict[str, float | int | None]:
    """Leverage inputs in USD, keyed like LeverageMetrics fields."""
    period = choose_flow_period(facts, form)
    debt = total_debt(facts)
    cash = facts.instant("cash")
    ebit = facts.duration("operating_income", period)
    depreciation = facts.duration("depreciation_amortization", period)
    interest = facts.duration("interest_expense", period)
    return {
        "total_debt": debt,
        "shareholders_equity": facts.instant("equity"),
        "total_assets": facts.instant("assets"),
        "net_debt": debt - cash if debt is not None and cash is not None else None,
        "ebit": ebit,
        "ebitda": ebit + depreciation if ebit is not None and depreciation is not None else None,
        "interest_expense": abs(interest) if interest is not None else None,
        "flow_period_months": period_months(period) if period else None,
    }


def valuation_values(facts: FilingFacts, form: str) -> dict[str, Any]:
    """Values for the valuation extraction schema, in millions (USD and shares)."""
    target_months = 12 if form.upper().startswith("10-K") else 3
    periods = facts.periods_for("operating_income") or facts.periods_for("revenue")
    period = next((p for p in periods if period_months(p) == target_months), None)

    def flow(key: str) -> float | None:
        return _millions(facts.duration(key, period))

    debt = total_debt(facts)
    cash = facts.instant("cash")
    securities = facts.instant("marketable_securities")
    operating_cash_flow = flow("operating_cash_flow")
    capex = flow("capital_expenditures")
    operating_income = flow("operating_income")
    depreciation = flow("depreciation_amortization")
    short_term = facts.instant("debt_current")
    if short_term is None:
        short_term = _sum(
            facts.instant("long_term_debt_current"),
            facts.instant("short_term_borrowings"),
            facts.instant("commercial_paper"),
        )
    interest = flow("interest_expense")

    return {
        "period_end": facts.period_end,
        "flow_period_months": period_months(period) if period else None,
        "revenue_margins": {
            "total_revenue": flow("revenue"),
            "cost_of_revenue": flow("cost_of_revenue"),
            "gross_profit": flow("gross_profit"),
            "operating_income": operating_income,
            "net_income": flow("net_income"),
        },
        "cash_flow": {
            "operating_cash_flow": operating_cash_flow,
            "capital_expenditures": capex,
            "free_cash_flow": (
                operating_cash_flow - capex
                if operating_cash_flow is not None and capex is not None
                else None
            ),
            "depreciation_amortization": depreciation,
            "stock_based_compensation": flow("stock_based_compensation"),
        },
        "debt_liquidity": {
            "total_debt": _millions(debt),
            "short_term_debt": _millions(short_term),
            "long_term_debt": _millions(facts.instant("long_term_debt_noncurrent")),
            "cash_and_equivalents": _millions(cash),
            "marketable_securities": _millions(securities),
            # Net of marketable securities, which are liquid and offset debt like cash.
            "net_debt": (
                _millions(debt - cash - (securities or 0.0)) if debt is not None and cash is not None else None
            ),
            "interest_expense": abs(interest) if interest is not None else None,
        },
        "capital_allocation": {
            "buyback_amount": flow("buybacks"),
            "dividends_paid": flow("dividends_paid"),
            "shares_outstanding_diluted": flow("diluted_shares"),
            "rd_expense": flow("rd_expense"),
        },
        "additional_metrics": {
            "ebit": operating_income,
            "ebitda": (
                operating_income + depreciation
                if operating_income is not None and depreciation is not None
                else None
            ),
            "total_assets": _millions(facts.instant("assets")),
            "shareholders_equity": _millions(facts.instant("equity")),
        },
    }


def trailing_twelve_months(company_facts: dict[str, Any], period_end: str | None) -> dict[str, Any]:
    """TTM flows in millions ending at period_end: latest fiscal year + current YTD - prior-year YTD.

    Unlike facts_for_filing, this reads prior-year comparatives (reported in the current filing
    or in earlier ones). Returns {} when the needed periods are not all available.
    """
    if not period_end:
        return {}
    gaap = company_facts.get("facts", {}).get("us-gaap", {})
    result: dict[str, Any] = {}
    for key in TTM_KEYS:
        value = _ttm_value(_duration_values(gaap, key), period_end)
        if value is not None:
            result[key] = _millions(abs(value) if key == "interest_expense" else value)
    if "operating_cash_flow" in result and "capital_expenditures" in result:
        result["free_cash_flow"] = round(result["operating_cash_flow"] - result["capital_expenditures"], 3)
    if "revenue" not in result and "operating_cash_flow" not in result:
        return {}
    return {"period_end": period_end, **result}


def _duration_values(gaap: dict[str, Any], key: str) -> dict[tuple[str, str], float]:
    """Duration facts for a concept, keyed by period; first alias wins, latest filing wins within one."""
    merged: dict[tuple[str, str], float] = {}
    for alias in CONCEPTS[key]:
        facts = gaap.get(alias, {}).get("units", {}).get(USD, [])
        by_period: dict[tuple[str, str], float] = {}
        for fact in sorted(facts, key=lambda f: f.get("filed", "")):
            if "start" in fact and isinstance(fact.get("val"), (int, float)):
                by_period[(fact["start"], fact["end"])] = float(fact["val"])
        for period, value in by_period.items():
            merged.setdefault(period, value)
    return merged


def _ttm_value(values: dict[tuple[str, str], float], period_end: str) -> float | None:
    year_to_date = [p for p in values if p[1] == period_end and 2 <= period_months(p) <= 12]
    if not year_to_date:
        return None
    current = max(year_to_date, key=_period_days)
    if period_months(current) == 12:
        return values[current]

    fiscal_year_end = date.fromisoformat(current[0]) - timedelta(days=1)
    fiscal_year = _find_period(values, start=None, end=fiscal_year_end, months=12)
    if fiscal_year is None:
        return None
    prior = _find_period(
        values,
        start=date.fromisoformat(fiscal_year[0]),
        end=date.fromisoformat(period_end) - timedelta(days=365),
        months=period_months(current),
    )
    if prior is None:
        return None
    return values[fiscal_year] + values[current] - values[prior]


def _find_period(
    values: dict[tuple[str, str], float],
    *,
    start: date | None,
    end: date,
    months: int,
) -> tuple[str, str] | None:
    """Period of the given length ending near end (and starting near start); tolerates 52/53-week years."""
    for period in values:
        if period_months(period) != months:
            continue
        if abs((date.fromisoformat(period[1]) - end).days) > 7:
            continue
        if start is not None and abs((date.fromisoformat(period[0]) - start).days) > 7:
            continue
        return period
    return None


def non_null_values(nested: dict[str, Any]) -> dict[str, Any]:
    """Drop None leaves (and empty sections) from a nested values dict."""
    result: dict[str, Any] = {}
    for key, value in nested.items():
        if isinstance(value, dict):
            inner = non_null_values(value)
            if inner:
                result[key] = inner
        elif value is not None:
            result[key] = value
    return result


def _first(values: dict[str, float], aliases: tuple[str, ...]) -> float | None:
    for alias in aliases:
        if alias in values:
            return values[alias]
    return None


def _sum(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _millions(value: float | None) -> float | None:
    return round(value / 1_000_000, 3) if value is not None else None


def _period_days(period: tuple[str, str]) -> int:
    start, end = (date.fromisoformat(part) for part in period)
    return (end - start).days + 1
