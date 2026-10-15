import filing_text as ft

FILLER = "<p>" + ("Lorem ipsum dolor sit amet. " * 40) + "</p>\n"


def _ten_k_html() -> str:
    toc = (
        "<table><tr><td>Item 1A.</td><td>Risk Factors</td><td>10</td></tr>"
        "<tr><td>Item 7.</td><td>Management&#8217;s Discussion and Analysis</td><td>20</td></tr>"
        "<tr><td>Item 8.</td><td>Financial Statements and Supplementary Data</td><td>30</td></tr></table>"
    )
    return (
        "<html><head><title>x</title></head><body>"
        "<div style='display:none'><ix:header><ix:hidden>XBRL JUNK fasb.org</ix:hidden></ix:header></div>"
        "<p>FORM 10-K</p>" + toc
        + "<p>Item 1A. Risk Factors</p>" + "<p>RISK CONTENT</p>" + FILLER * 5
        + "<p>Item 7. Management&#8217;s Discussion and Analysis</p>" + "<p>MDNA CONTENT</p>" + FILLER * 5
        + "<p>Item 8. Financial Statements and Supplementary Data</p>"
        + "<p>Report of Independent Registered Public Accounting Firm</p>" + FILLER
        + "<p>CONSOLIDATED BALANCE SHEETS</p>"
        + "<table><tr><td>Long-term debt</td><td>$</td><td>128,894</td></tr></table>"
        + FILLER * 5
        + "<p>Item 9. Changes in and Disagreements</p>" + FILLER
        + "</body></html>"
    )


def test_html_to_text_cleans_markup():
    raw = (
        "<html><head><style>.x{}</style></head><body>"
        "<ix:header>hidden xbrl</ix:header><script>var a;</script>"
        "<p>Caf&eacute;&#160;sales</p>"
        "<table><tr><td>Net income</td><td>$</td><td>1,234</td><td>(</td><td>56</td><td>)</td></tr></table>"
        "<p>Table of Contents</p><p>42</p>"
        "</body></html>"
    )
    text = ft.html_to_text(raw)
    assert "hidden xbrl" not in text and "var a" not in text
    assert "Café sales" in text
    assert "Net income | $1,234" in text
    assert "Table of Contents" not in text and "\n42\n" not in f"\n{text}\n"


def test_periodic_excerpt_selects_sections_and_skips_toc_and_audit_report():
    excerpt = ft.build_filing_excerpt("10-K", _ten_k_html(), max_chars=6000)
    assert "XBRL JUNK" not in excerpt
    assert "[Management's Discussion and Analysis]" in excerpt
    assert "MDNA CONTENT" in excerpt
    assert "RISK CONTENT" in excerpt
    assert "Long-term debt | $128,894" in excerpt
    assert "Report of Independent Registered" not in excerpt
    assert len(excerpt) <= 6000


def test_short_filing_is_returned_whole():
    assert ft.build_filing_excerpt("10-Q", "<p>Tiny filing</p>", max_chars=1000) == "Tiny filing"


def test_8k_excerpt_includes_labelled_exhibits():
    exhibits = [ft.ExhibitText("EX-99.1", "Press release", "<p>Revenue grew 10%</p>")]
    excerpt = ft.build_filing_excerpt("8-K", "<p>Item 2.02 Results</p>", exhibits, max_chars=2000)
    assert "[8-K primary document]" in excerpt
    assert "[Exhibit EX-99.1: Press release]" in excerpt
    assert "Revenue grew 10%" in excerpt
