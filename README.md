# AI Investment Thesis evaluation system

An Investment Thesis evaluation system that utilizes OpenAI API based on SEC filings and other financial data. The system is designed to analyze and evaluate investment theses for publicly traded companies by leveraging natural language processing and machine learning techniques.

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
```

## Set Environment Variable for OpenAI API Key

```bash
# PowerShell
$env:OPENAI_API_KEY="your_openai_api_key"

# Windows
set OPENAI_API_KEY=your_openai_api_key

# Linux / MacOS
export OPENAI_API_KEY=your_openai_api_key
```

## Set Environment Variable for SEC Filing API

This project reads company filings directly from SEC EDGAR. The SEC requires automated clients to identify themselves with a descriptive `User-Agent` header that includes contact information. This is necessary because SEC services monitor automated access and may reject or throttle requests that do not identify the caller properly.

Set `SEC_USER_AGENT` before running the script:

```bash
# PowerShell
$env:SEC_USER_AGENT="ai-investment-thesis/1.0 your-email@example.com"

# Windows
set SEC_USER_AGENT=ai-investment-thesis/1.0 your-email@example.com

# Linux / MacOS
export SEC_USER_AGENT="ai-investment-thesis/1.0 your-email@example.com"
```

Use a real email address or other valid contact detail in the value. The SEC client in [sec_filings.py](sec_filings.py) will fail at startup if this variable is missing.

## How The System Works

The system is a batch thesis revalidation pipeline driven by new SEC filings.

At a high level, the workflow is:

1. `main.py` scans all markdown files in [thesis](thesis).
2. The ticker is derived from the thesis file name, so `amzn.md` maps to `AMZN`, `nvda.md` maps to `NVDA`, and so on.
3. For every thesis, the script uses [sec_filings.py](sec_filings.py) to look up the company on SEC EDGAR and retrieve recent `10-K`, `10-Q`, and `8-K` filings.
4. The script checks whether a filing has already been processed by searching the thesis markdown for a hidden accession marker in the Decision Log.
5. Only filings that do not already have a processed marker are treated as new filings.
6. For each new filing, the script loads the corresponding review instructions from [instructions/10-k.md](instructions/10-k.md), [instructions/10-q.md](instructions/10-q.md), or [instructions/8-k.md](instructions/8-k.md).
7. The filing text, the full current thesis, and the selected instruction file are sent to the OpenAI evaluation layer in [openai_evaluator.py](openai_evaluator.py).
8. The OpenAI evaluator produces a short markdown review intended to be appended to the thesis Decision Log.
9. The script appends a new Decision Log entry that includes the filing type, filing date, accession number, filing URL, processing date, and the OpenAI-generated evaluation.
10. A hidden processed marker is stored alongside the new entry so the same SEC filing will not be processed again in a future run.

### Core Components

`main.py`

- Orchestrates the end-to-end workflow.
- Iterates through all thesis files.
- Detects new filings.
- Calls the evaluator.
- Writes updated decision logs back to disk.
- Prints progress and summary information during the run.

`sec_filings.py`

- Resolves tickers to SEC CIK values.
- Lists available `10-K`, `10-Q`, and `8-K` filings.
- Fetches the primary filing document from SEC EDGAR.
- Enforces the requirement that `SEC_USER_AGENT` must be configured.

`openai_evaluator.py`

- Wraps the OpenAI API call.
- Builds the evaluation prompt from three inputs: the thesis markdown, the SEC filing text, and the form-specific instruction file.
- Returns markdown suitable for inclusion in the thesis Decision Log.

`instructions/`

- Contains the review framework for each filing type.
- `10-k.md` is used for annual revalidation.
- `10-q.md` is used for quarterly revalidation.
- `8-k.md` is used for event-driven evaluation.

`thesis/`

- Stores one markdown file per company thesis.
- Each file contains the long-form thesis and a `## Decision Log` section.
- New SEC-driven reviews are appended to the Decision Log over time.

### How Reprocessing Is Prevented

Every generated Decision Log entry includes a hidden marker in this format:

```markdown
<!-- processed-sec-filing:0000000000-00-000000 -->
```

That accession number is unique to the SEC filing. On the next run, the script scans the thesis file for that marker. If the marker already exists, the filing is skipped.

This makes the process idempotent for previously handled filings and ensures the script only evaluates newly discovered filings.

### What Gets Written To The Thesis

For each new SEC filing, the script appends a new Decision Log block with:

- the filing form, date, and accession number
- the filing URL on sec.gov
- the processing date
- the OpenAI-generated thesis evaluation

This creates a durable audit trail showing which filing drove each new decision log entry.

### Runtime Output

When you run the script, it prints operational progress to the console, including:

- which thesis file is currently being processed
- how many relevant SEC filings were discovered
- which filings are new
- a short summary of the OpenAI result for each processed filing
- final totals for processed filings, skipped theses, and failures

### Requirements Summary

The script depends on both of these environment variables being configured before execution:

- `OPENAI_API_KEY` for the OpenAI API
- `SEC_USER_AGENT` for SEC EDGAR access

Without `OPENAI_API_KEY`, the evaluator cannot produce decision log content. Without `SEC_USER_AGENT`, the SEC client will refuse to start.

## Run the Application

```bash
# Ensure OPENAI_API_KEY and SEC_USER_AGENT are set first
python main.py

# Limit the filing scan depth per thesis
python main.py --filings-limit 10

# Override the OpenAI model for this run
python main.py --openai-model gpt-4.1-mini
```
