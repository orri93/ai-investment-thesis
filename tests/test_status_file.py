import status_file as sf

STATUS = (
    "# AMZN Thesis Status\n\n"
    "<!-- status-source-accession:ACC -->\n- Verdict: Hold\n\n"
    "## Latest assessment\n- Summary.\n\n"
    "## WARNING\nText\n"
)
BLOCK = [sf.LEVERAGE_STATUS_START_MARKER, "### Latest leverage assessment", "- Leverage category: Low",
         sf.LEVERAGE_STATUS_END_MARKER]


def test_insert_places_block_at_end_of_latest_assessment():
    result = sf.insert_leverage_block(STATUS, BLOCK)
    assert result.index("- Summary.") < result.index(sf.LEVERAGE_STATUS_START_MARKER) < result.index("## WARNING")
    assert sf.extract_leverage_block(result) == BLOCK


def test_insert_is_idempotent_and_replaces_existing_block():
    once = sf.insert_leverage_block(STATUS, BLOCK)
    assert sf.insert_leverage_block(once, BLOCK) == once
    new_block = BLOCK[:2] + ["- Leverage category: High"] + BLOCK[3:]
    replaced = sf.insert_leverage_block(once, new_block)
    assert replaced.count(sf.LEVERAGE_STATUS_START_MARKER) == 1
    assert "High" in replaced and "Low" not in replaced


def test_insert_returns_none_without_latest_assessment_section():
    assert sf.insert_leverage_block("# Status\n- Verdict: Hold\n", BLOCK) is None


def test_remove_leverage_blocks_strips_every_block():
    text = sf.insert_leverage_block(STATUS, BLOCK) + "\n".join(BLOCK) + "\n"
    cleaned = sf.remove_leverage_blocks(text)
    assert sf.LEVERAGE_STATUS_START_MARKER not in cleaned
    assert sf.extract_leverage_block(cleaned) is None
