# SEC-Driven Investment Thesis Revalidation (OpenAI + EDGAR)

An Investment Thesis evaluation system that utilizes OpenAI API based on SEC filings and other financial data. The system is designed to analyze and evaluate investment theses for publicly traded companies by leveraging natural language processing and machine learning techniques.

## Who This Is For / Not For

**This tool is for you if:**
- You write investment theses or memos before buying a stock
- You want a structured, repeatable way to revisit your thesis when new filings drop
- You value an audit trail - knowing *why* you held, trimmed, or exited a position
- You are comfortable setting up a Python environment and an OpenAI API key

**This tool is not for you if:**
- You are looking for stock picks or trading signals
- You want fully automated buy/sell decisions
- You expect the output to substitute for professional financial advice

Outputs are evidence-based summaries grounded in SEC filings, not investment recommendations. See [LEGAL-DISCLAIMER.md](LEGAL-DISCLAIMER.md) for full details.

## Demo

See [demo.md](demo.md) for a step-by-step walkthrough of the full workflow, covering thesis generation, evaluation, and leverage analysis.

## Legal Notice

Before using this project, please read [LEGAL-DISCLAIMER.md](LEGAL-DISCLAIMER.md) in full.

By using this system, you acknowledge that outputs are advisory and educational, not investment advice, and that use is at your own risk.

## Python Environment

Create the Virtual Environment
```bash
python -m venv venv
```
Activate the Virtual Environment
```bash
# Windows
venv\Scripts\activate

# Linux / MacOS
source venv/bin/activate
```

Install the Requirements
```bash
pip install -r requirements.txt

# For development (adds pytest)
pip install -r requirements-dev.txt
```

## Configuration (.env)

All scripts read their settings from a `.env` file in the project root. The file is git-ignored, so your credentials never end up in version control.

1. Copy [.env.example](.env.example) to `.env`.
2. Fill in your values:

```bash
OPENAI_API_KEY=your_openai_api_key
SEC_USER_AGENT=ai-investment-thesis/1.0 your-email@example.com
# Optional: default model for all scripts
OPENAI_MODEL=gpt-6.1-sol
```

Variables that are already set in the environment take precedence over `.env`, so you can still override a value for one run:

```bash
# PowerShell
$env:OPENAI_MODEL="gpt-4.1-mini"

# Windows
set OPENAI_MODEL=gpt-4.1-mini

# Linux / MacOS
export OPENAI_MODEL=gpt-4.1-mini
```

### Why SEC_USER_AGENT Is Required

This project reads company filings directly from SEC EDGAR. The SEC requires automated clients to identify themselves with a descriptive `User-Agent` header that includes contact information. This is necessary because SEC services monitor automated access and may reject or throttle requests that do not identify the caller properly.

Use a real email address or other valid contact detail in the value. The SEC client in [sec_filings.py](sec_filings.py) will fail at startup if this variable is missing. The client also keeps requests below the SEC limit of 10 per second and retries temporary failures (HTTP 429/5xx and network errors) with backoff.

## Quick Start: Launch Scripts

The launch scripts activate the virtual environment and run the application. They contain no credentials (those live in `.env`), so you can run them directly:

- **Windows:** `.\evaluate.ps1`, `.\leverage-evaluate.ps1`, `.\generate.ps1 <draft-file>`
- **Linux/macOS:** `./evaluate.sh`, `./leverage-evaluate.sh`, `./generate.sh <draft-file>` (run `chmod +x *.sh` once)

Extra arguments are passed through, for example `.\evaluate.ps1 --verbose`.

## How The System Works

The system is a batch thesis revalidation pipeline driven by new SEC filings.

At a high level, the workflow is:

1. `main.py` scans all markdown files in [thesis](thesis).
2. The ticker is derived from the thesis file name, so `amzn.md` maps to `AMZN`, `nvda.md` maps to `NVDA`, and so on.
3. For every thesis, the script uses [sec_filings.py](sec_filings.py) to look up the company on SEC EDGAR and retrieve recent `10-K`, `10-Q`, and `8-K` filings, newest first. Filings dated before the thesis `Purchased:` date are skipped. The first run scans `--filings-limit` filings (default 25); later runs keep scanning past that limit until they reach a filing already in the log, so a backlog is never skipped.
4. The script writes and reads evaluation logs in same-named files under [log](log), for example `thesis/amzn.md` -> `log/amzn.md`.
5. Only filings that do not already have a processed marker are treated as new filings.
6. For each new filing, the script loads the corresponding review instructions from [instructions/10-k.md](instructions/10-k.md), [instructions/10-q.md](instructions/10-q.md), or [instructions/8-k.md](instructions/8-k.md).
7. The filing is converted to plain text by [filing_text.py](filing_text.py). For `10-K`/`10-Q` filings the excerpt is built from the key sections (MD&A, financial statements, risk factors, market risk) within the size budget; for `8-K` filings the `EX-99` exhibits (for example the earnings press release) are included alongside the cover document. That excerpt, the full current thesis, and the selected instruction file are sent to the OpenAI evaluation layer in [openai_evaluator.py](openai_evaluator.py).
8. The OpenAI evaluator produces a short markdown review intended to be appended to the log file Evaluation Log.
9. The script appends a new Evaluation Log entry to the log file that includes the filing type, filing date, accession number, filing URL, processing date, and the OpenAI-generated evaluation.
10. A hidden processed marker is stored alongside the new entry so the same SEC filing will not be processed again in a future run.
11. If the thesis file was edited since the last run, the latest `10-K`/`10-Q` is re-reviewed against the revised thesis (see [Thesis Revisions](#thesis-revisions)).
12. The thesis status file in [status](status) is regenerated from the latest relevant log entry whenever that entry changes.

### Core Components

`main.py`

- Orchestrates the end-to-end workflow.
- Iterates through all thesis files.
- Detects new filings and thesis edits.
- Calls the evaluator.
- Writes updated evaluation logs to [log](log) files and status files to [status](status).
- Prints progress and summary information during the run.

`sec_filings.py`

- Resolves tickers to SEC CIK values.
- Lists available `10-K`, `10-Q`, and `8-K` filings.
- Fetches the primary filing document from SEC EDGAR.
- Lists a filing's documents from its index page and downloads exhibits (such as `EX-99.1`).
- Downloads XBRL company facts (as-reported financial values).
- Throttles and retries requests, and enforces the requirement that `SEC_USER_AGENT` must be configured.

`openai_evaluator.py`

- Wraps the OpenAI API call.
- Builds the evaluation prompt from three inputs: the thesis markdown, the SEC filing text, and the form-specific instruction file.
- Returns markdown suitable for inclusion in the log file Evaluation Log.
- Also contains the leverage extraction, ratio, and report logic used by `leverage-evaluator.py`.

Supporting modules

- [filing_text.py](filing_text.py): converts filing HTML to text and builds section-aware excerpts.
- [xbrl_facts.py](xbrl_facts.py): selects as-reported XBRL values for one filing (debt, equity, assets, operating income, D&A, interest, cash flows).
- [status_file.py](status_file.py): finds, removes, and inserts the leverage block in status files.
- [openai_support.py](openai_support.py): shared OpenAI client creation and request handling.
- [utils.py](utils.py): shared helpers, `.env` loading, and atomic file writes (logs and status files are written to a temporary file and then renamed, so a crash never leaves a half-written file).

`instructions/`

- Contains the review framework for each filing type.
- `10-k.md` is used for annual revalidation.
- `10-q.md` is used for quarterly revalidation.
- `8-k.md` is used for event-driven evaluation.

`thesis/`

- Stores one markdown file per company thesis.
- Files are the source investment-thesis documents used as evaluation input.

`log/`

- Stores one markdown file per company for generated evaluation logs.
- Each log file is named the same as the thesis file (for example `amzn.md`).
- If a log file does not exist, it is created automatically with:
	- a top-level header from the thesis ticker/file name (for example `# AMZN`)
	- a `## Evaluation Log` header

`status/`

- Stores one status file per thesis (for example `status/amzn.md`), with the overall status (Green/Yellow/Red), verdict, thesis validity, per-part ratings, and a one-line latest assessment.
- Regenerated from the latest relevant log entry: every `10-K`/`10-Q` review, and `8-K` reviews unless they are informational / No Action.
- The source marker and `Updated on` date are always set by the code, not the model. If the model's reply is unusable, a fallback status is built from the evaluation's own verdict.
- `leverage-evaluator.py` adds a leverage block to existing status files; `main.py` preserves it when it regenerates the status.
- Use `--status-dir` to write status files elsewhere.

### Thesis Revisions

The log stores a fingerprint (SHA-256) of the thesis in a hidden marker:

```markdown
<!-- thesis-sha256:... -->
```

When the thesis file changes, the next run re-reviews the latest `10-K` or `10-Q` against the revised thesis and appends a `### Thesis Revision Review` entry. That entry then drives the status file. If a new `10-K`/`10-Q` was already reviewed in the same run, no extra review is needed. The first run after upgrading only records the fingerprint; it does not re-review every thesis. Whitespace and line-ending changes are ignored.

### How Reprocessing Is Prevented

Every generated Evaluation Log entry includes a hidden marker in this format:

```markdown
<!-- processed-sec-filing:0000000000-00-000000 -->
```

That accession number is unique to the SEC filing. On the next run, the script scans the corresponding log file for that marker. If the marker already exists, the filing is skipped.

This makes the process idempotent for previously handled filings and ensures the script only evaluates newly discovered filings.

### What Gets Written To The Log File

For each new SEC filing, the script appends a new Evaluation Log block to the `log/<ticker>.md` file with:

- the filing form, date, and accession number
- the filing URL on sec.gov
- the processing date
- the OpenAI-generated thesis evaluation

This creates a durable audit trail showing which filing drove each new evaluation log entry.

### Runtime Output

When you run the script, it prints operational progress to the console, including:

- which thesis file is currently being processed
- how many relevant SEC filings were discovered
- which filings are new
- a short summary of the OpenAI result for each processed filing
- final totals for processed filings, skipped theses, and failures

### Requirements Summary

The script depends on both of these settings being configured (in `.env` or the environment) before execution:

- `OPENAI_API_KEY` for the OpenAI API
- `SEC_USER_AGENT` for SEC EDGAR access

Without `OPENAI_API_KEY`, the evaluator cannot produce evaluation log content. Without `SEC_USER_AGENT`, the SEC client will refuse to start.

## Create Your Own Thesis Files

You can create your own theses by using templates in [thesis-examples](thesis-examples).

### Quick Start: Generate a Thesis with AI

The `thesis-generator.py` script helps you complete and improve draft theses using OpenAI:

```bash
# Create a draft with just your initial idea or some notes
python thesis-generator.py thesis/my-company-draft.md
```

You can also run the launch scripts (credentials come from `.env`):

```bash
# Windows PowerShell
.\generate.ps1 .\thesis\my-company-draft.md

# Linux / macOS
./generate.sh ./thesis/my-company-draft.md
```

The script will:
1. Read your draft (can be incomplete, just an idea, or partially written)
2. Use OpenAI with web search to research the company
3. Refine and complete your thesis with proper structure, using the completed examples in [thesis-examples](thesis-examples) (drafts and the generic template are not used as examples)
4. Save your original draft as `<file>.md.bak` and overwrite the file with the completed thesis

**Note:** Ensure `OPENAI_API_KEY` is set before running.

**Example draft thesis:** See [thesis-examples/pltr-draft.md](thesis-examples/pltr-draft.md) to understand what a draft thesis input looks like. This is a minimal starting point that the generator will expand into a complete thesis.

### Manual Thesis Creation

Recommended starting points:

- [thesis-examples/general-thesis.md](thesis-examples/general-thesis.md): generic template
- [thesis-examples/amzn.md](thesis-examples/amzn.md): concrete company example
- [thesis-examples/nvda.md](thesis-examples/nvda.md): concrete company example

Steps for manual thesis creation:

1. Copy [thesis-examples/general-thesis.md](thesis-examples/general-thesis.md) to a new file in [thesis](thesis).
2. Name the file as the ticker in lowercase, for example `msft.md`, `goog.md`, or `wmt.md`.
3. Fill out the thesis sections (position, core thesis, risks, invalidation criteria, and so on).
4. A top-level company header is optional; log initialization uses the thesis file name as ticker.
5. Run the script with `python main.py`.
6. Review generated entries in `log/<ticker>.md`.

## Run the Application

```bash
# Ensure OPENAI_API_KEY and SEC_USER_AGENT are set first (.env or environment)
python main.py

# Scan depth for the first run per thesis (later runs catch up with the log automatically)
python main.py --filings-limit 10

# Override the OpenAI model for this run
python main.py --openai-model gpt-4.1-mini

# Write logs and status files to custom folders
python main.py --log-dir my-logs --status-dir my-status

# Print full tracebacks for unexpected errors (all scripts support --verbose)
python main.py --verbose
```

## Leverage Evaluator (Helper Tool)

The leverage evaluator is a separate helper workflow and **not part of the original thesis evaluator pipeline** in `main.py`.

- Main thesis evaluator: `main.py` writes filing review output to [log](log)
- Leverage helper evaluator: `leverage-evaluator.py` writes leverage history output to [leverage](leverage)

### Run Leverage Evaluator Directly

```bash
# Uses thesis/*.md tickers, fetches latest 10-K or 10-Q, writes leverage/<ticker>.md
python leverage-evaluator.py

# Optional flags
python leverage-evaluator.py --filings-limit 25 --openai-model gpt-4.1-mini
```

### Use Leverage Launch Scripts

Run `.\leverage-evaluate.ps1` (Windows) or `./leverage-evaluate.sh` (Linux/macOS). Credentials come from `.env`.

### What It Produces

- One leverage history file per ticker in [leverage](leverage), named like the thesis file (for example `googl.md`).
- Each entry references the SEC filing URL, filing accession number, and processing date.
- Reprocessing is prevented with a processed marker (`processed-leverage-filing:<accession>`), so the same filing is not evaluated again.
- If an existing `status/<ticker>.md` file is missing the leverage block for the latest processed filing, it is restored from the leverage log without calling OpenAI. `main.py` preserves this block when it regenerates a status file.
- Debt, equity, assets, cash, operating income (EBIT), D&A (for EBITDA), and interest expense come from SEC XBRL data reported in that filing when available. The AI extraction from the filing text (no web search) only fills gaps. The Extracted Values table shows the source of each value.
- For `10-Q` filings, EBITDA is annualized before computing Net Debt / EBITDA. The rule-based category uses the thresholds in [instructions/leverage.md](instructions/leverage.md): High if any available ratio is in the high range, Low only if every available ratio is in the low range. The report's verdict is asked to follow it.

## Valuation Models (Helper Tool)

`valuation-models.py` builds a valuation document per ticker in [valuation](valuation) from several years of filings:

1. Extracts financial data from each `10-K`/`10-Q`. As-reported SEC XBRL values (revenue, operating income, cash flows, debt, cash, equity, and more) are authoritative; the AI extraction from the filing text fills the remaining fields.
2. Computes trailing-twelve-month cash flows and income from XBRL (latest fiscal year + current year-to-date - prior-year year-to-date) and retrieves market inputs once by web search (share price, risk-free rate, beta, equity risk premium, each cited with source and date). Net debt deducts marketable securities.
3. Builds valuation models (DCF on a normalized terminal year, normalized earnings, scenarios) and reconciles them with the market price through a reverse DCF.
4. Assesses qualitative value drivers from the filings.
5. Connects recent filings to valuation impact.

```bash
python valuation-models.py
python valuation-models.py --ticker amzn --10k-years 3 --10q-quarters 4 --8k-months 12 --openai-model gpt-6.1-sol
```

## Running Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The tests cover the parsers, status handling, XBRL selection, SEC client retry/throttling, OpenAI retry behavior, and thesis revision logic. They make no network or OpenAI calls.
