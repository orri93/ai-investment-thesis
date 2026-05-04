Create a complete thesis status markdown document from the provided SEC evaluation markdown.

Goal:
- Convert one already-generated SEC evaluation into a stable status file.
- Do not invent facts beyond the provided evaluation text.
- If the evaluation is positive or thesis-intact, do not mark the thesis as broken.

Output format (use exactly these sections and bullets):

# <TICKER> Thesis Status

<!-- status-source-accession:<ACCESSION_NUMBER> -->
- Source filing: <FORM> (<FILING_DATE>) - <ACCESSION_NUMBER>
- Updated on: <YYYY-MM-DD>
- Overall status: <Green|Yellow|Red>
- Verdict: <Add|Hold|Trim|Exit|No Action|Watch|Reduce|Maintain>
- Thesis validity: <Intact|Broken>

## Parts
- <Part label 1>: <Green|Yellow|Red>
- <Part label 2>: <Green|Yellow|Red>

## Latest assessment
- <One concise summary sentence based on the SEC evaluation>

[optional only if broken]
## WARNING
THESIS IS BROKEN based on the latest relevant SEC filing.
Reason: <clear reason grounded in the SEC evaluation>

Rules:
1) Use the verdict from the evaluation when explicitly present.
2) If verdict is missing, infer the closest valid verdict from the evaluation tone.
3) "Thesis validity: Broken" is allowed only when the evaluation clearly indicates thesis breakage, invalidation, or an Exit-equivalent conclusion.
4) Positive/strong results should generally map to Intact and Green/Yellow unless explicit severe negatives exist.
5) Keep "Latest assessment" to one bullet line.
6) Keep the output concise and consistent.
7) Return markdown only, no code fences.
