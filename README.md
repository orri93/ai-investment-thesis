# ai-investment-thesis
An Investment Thesis evaluation system that utilizes OpenAI API

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

## SEC Filings Module

The project now includes a small SEC EDGAR client in `sec_filings.py` that can:

- resolve a ticker to a SEC CIK
- check whether 10-K, 10-Q, and 8-K filings are available
- list recent filings for those forms
- fetch or download the primary filing document from sec.gov

SEC expects a descriptive `User-Agent` header with contact information. Set it before using the module:

```bash
# PowerShell
$env:SEC_USER_AGENT="ai-investment-thesis/1.0 your-email@example.com"

# Windows
set SEC_USER_AGENT=ai-investment-thesis/1.0 your-email@example.com

# Linux / MacOS
export SEC_USER_AGENT="ai-investment-thesis/1.0 your-email@example.com"
```

Example usage:

```python
from sec_filings import SecFilingsClient

client = SecFilingsClient()

if client.is_filing_available("NVDA", "10-K"):
	latest_10k = client.find_filing("NVDA", form="10-K")
	print(latest_10k.filing_date, latest_10k.primary_document_url)

document = client.fetch_filing("NVDA", form="10-Q")
print(document.text[:500])
```

To save a filing locally:

```python
client.download_filing("NVDA", "downloads/nvda-8k.html", form="8-K")
```

## Run the Application

```bash
# Ensure SEC_USER_AGENT is set first
python main.py

# Test a specific ticker and fetch a filing preview
python main.py AMZN --form 10-Q --fetch
```
