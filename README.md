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

## Quick Start: Using Evaluate Scripts

This project includes example evaluation scripts that set up the environment and run the application:

- **Windows:** `evaluate-example.ps1`
- **Linux/macOS:** `evaluate-example.sh`

To create a private version with your actual credentials:

### For Windows

1. Copy `evaluate-example.ps1` to `evaluate.ps1` (this file is git-ignored)
2. Open `evaluate.ps1` in your editor
3. Replace the placeholder values:
   - `your_openai_api_key` → your actual OpenAI API key
   - `your-email@example.com` → your actual email address
4. Run the script: `.\evaluate.ps1`

### For Linux/macOS

1. Copy `evaluate-example.sh` to `evaluate.sh` (this file is git-ignored)
2. Make it executable: `chmod +x evaluate.sh`
3. Open `evaluate.sh` in your editor
4. Replace the placeholder values:
   - `your_openai_api_key` → your actual OpenAI API key
   - `your-email@example.com` → your actual email address
5. Run the script: `./evaluate.sh`

The example scripts are safe to commit to version control; the private versions containing your credentials should never be committed.

## How The System Works

The system is a batch thesis revalidation pipeline driven by new SEC filings.

At a high level, the workflow is:

1. `main.py` scans all markdown files in [thesis](thesis).
2. The ticker is derived from the thesis file name, so `amzn.md` maps to `AMZN`, `nvda.md` maps to `NVDA`, and so on.
3. For every thesis, the script uses [sec_filings.py](sec_filings.py) to look up the company on SEC EDGAR and retrieve recent `10-K`, `10-Q`, and `8-K` filings.
4. The script writes and reads evaluation logs in same-named files under [log](log), for example `thesis/amzn.md` -> `log/amzn.md`.
5. Only filings that do not already have a processed marker are treated as new filings.
6. For each new filing, the script loads the corresponding review instructions from [instructions/10-k.md](instructions/10-k.md), [instructions/10-q.md](instructions/10-q.md), or [instructions/8-k.md](instructions/8-k.md).
7. The filing text, the full current thesis, and the selected instruction file are sent to the OpenAI evaluation layer in [openai_evaluator.py](openai_evaluator.py).
8. The OpenAI evaluator produces a short markdown review intended to be appended to the log file Evaluation Log.
9. The script appends a new Evaluation Log entry to the log file that includes the filing type, filing date, accession number, filing URL, processing date, and the OpenAI-generated evaluation.
10. A hidden processed marker is stored alongside the new entry so the same SEC filing will not be processed again in a future run.

### Core Components

`main.py`

- Orchestrates the end-to-end workflow.
- Iterates through all thesis files.
- Detects new filings.
- Calls the evaluator.
- Writes updated evaluation logs to [log](log) files.
- Prints progress and summary information during the run.

`sec_filings.py`

- Resolves tickers to SEC CIK values.
- Lists available `10-K`, `10-Q`, and `8-K` filings.
- Fetches the primary filing document from SEC EDGAR.
- Enforces the requirement that `SEC_USER_AGENT` must be configured.

`openai_evaluator.py`

- Wraps the OpenAI API call.
- Builds the evaluation prompt from three inputs: the thesis markdown, the SEC filing text, and the form-specific instruction file.
- Returns markdown suitable for inclusion in the log file Evaluation Log.

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

The script depends on both of these environment variables being configured before execution:

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

You can also run the helper scripts:

```bash
# Windows PowerShell
.\generate.ps1 .\thesis\my-company-draft.md

# Linux / macOS
./generate.sh ./thesis/my-company-draft.md
```

To keep credentials private, copy and edit the example script first:

- Windows: copy `generate-example.ps1` to `generate.ps1`, add your real values, then run `./generate.ps1 <draft-file>`
- Linux/macOS: copy `generate-example.sh` to `generate.sh`, add your real values, then run `./generate.sh <draft-file>`

The script will:
1. Read your draft (can be incomplete, just an idea, or partially written)
2. Use OpenAI to research the company online if needed
3. Refine and complete your thesis with proper structure
4. Return a professional, investment-ready thesis document

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
# Ensure OPENAI_API_KEY and SEC_USER_AGENT are set first
python main.py

# Limit the filing scan depth per thesis
python main.py --filings-limit 10

# Override the OpenAI model for this run
python main.py --openai-model gpt-4.1-mini

# Write logs to a custom folder
python main.py --log-dir my-logs
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

### Use Leverage Helper Scripts

This project includes helper scripts for leverage evaluation setup and execution:

- Windows: `leverage-evaluate-example.ps1`
- Linux/macOS: `leverage-evaluate-example.sh`

To keep credentials private, copy and edit the example script first:

1. Windows:
   - Copy `leverage-evaluate-example.ps1` to `leverage-evaluate.ps1` (private)
   - Replace `your_openai_api_key` and `your-email@example.com`
   - Run: `./leverage-evaluate.ps1`
2. Linux/macOS:
   - Copy `leverage-evaluate-example.sh` to `leverage-evaluate.sh` (private)
   - `chmod +x leverage-evaluate.sh`
   - Replace `your_openai_api_key` and `your-email@example.com`
   - Run: `./leverage-evaluate.sh`

### What It Produces

- One leverage history file per ticker in [leverage](leverage), named like the thesis file (for example `googl.md`).
- Each entry references the SEC filing URL, filing accession number, and processing date.
- Reprocessing is prevented with a processed marker (`processed-leverage-filing:<accession>`), so the same filing is not evaluated again.
