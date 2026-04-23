# Canonical Demo

This is a short end-to-end demo showing:

1. Initializing private helper scripts
2. Generating a thesis from a draft
3. Running the main thesis evaluator
4. Viewing the resulting evaluation log entry

## 1) Initialization: Create Private Helper Scripts

Create private/local helper scripts from the example scripts before running the demo.

```bash
# Windows PowerShell
Copy-Item generate-example.ps1 generate.ps1
Copy-Item evaluate-example.ps1 evaluate.ps1
Copy-Item leverage-evaluate-example.ps1 leverage-evaluate.ps1

# Linux/macOS
cp generate-example.sh generate.sh
cp evaluate-example.sh evaluate.sh
cp leverage-evaluate-example.sh leverage-evaluate.sh
chmod +x generate.sh evaluate.sh leverage-evaluate.sh
```

Then edit the private scripts to set your real credentials:

- OPENAI_API_KEY
- SEC_USER_AGENT

## 2) Draft Thesis Input (Generator)

Source file: [thesis-examples/pltr-draft.md](thesis-examples/pltr-draft.md)

Important: Do not run the generator on the example draft as-is. First update the copied draft with your own private position information and your own investment justification.

```bash
# Copy draft into thesis/ using ticker filename
cp thesis-examples/pltr-draft.md thesis/pltr.md

# Edit thesis/pltr.md with your own:
# - position details (shares, entry, cost basis, portfolio weight)
# - core thesis and risk/invalidation views

# Generate/refine thesis from draft (overwrites thesis/pltr.md)
python thesis-generator.py thesis/pltr.md

# Alternative using private helper scripts
# Windows PowerShell
.\generate.ps1 .\thesis\pltr.md

# Linux/macOS
./generate.sh ./thesis/pltr.md
```

## 3) Thesis File Input (Main Evaluator)

Source file: [thesis/pltr.md](thesis/pltr.md)

This file can come from either:

1. The generated output from Step 2 (`python thesis-generator.py thesis/pltr.md`)
2. A manually written thesis created from scratch using templates in [thesis-examples](thesis-examples)

```markdown
# Palantir Technologies Inc (PLTR)

## Position

- [Number of shares or investment amount]
- [Purchased/Entry date]
- [Cost basis or investment details]
- [Approx. portfolio weight]

## What Palantir is

Palantir Technologies is a leading data analytics and software company specializing in large-scale data integration, analysis, and operational decision support. Its two core platforms, Gotham and Foundry, serve primarily government intelligence, defense agencies, and large commercial enterprises by enabling them to integrate disparate data sources, generate actionable insights, and improve complex operational workflows. Palantir’s software is highly customizable and focuses on use cases such as national security, fraud detection, supply chain optimization, and predictive maintenance.

The company has evolved from serving primarily U.S. government clients to aggressively expanding into commercial sectors including healthcare, energy, manufacturing, and finance. A key differentiator is Palantir’s ability to deliver end-to-end data solutions for complex, mission-critical problems that demand accuracy, speed, and customization. Palantir is also investing heavily in embedding AI and machine learning within its platforms to enhance automation and predictive analytics capabilities, aiming to capture the growth opportunity around enterprise AI adoption.  

## Core investment thesis

Palantir can compound shareholder value by capitalizing on the secular trends of increasing data complexity, rising global geopolitical risks, and AI-driven digital transformation across governments and enterprises. Its platforms provide essential infrastructure for customers tackling complex data integration and analysis challenges, which creates strong switching costs and long sales cycles with high renewal and expansion potential. The company’s unique ability to embed deeply within operational workflows drives sticky, mission-critical software adoption.

Growth over the next 5-10 years should be powered by accelerated commercial customer expansion, increasing AI and machine learning adoption across its platforms, and sustained government spending on security and intelligence capabilities amid escalating global geopolitical instability. Palantir also benefits from network effects as more organizations standardize on its technology stack, increasing barriers to entry for competitors. The combination of recurring revenue from subscription and services contracts, plus operational leverage from improving profit margins, underpins an attractive long-term compounder profile.

## Why Palantir specifically (company-level edge)

Palantir’s durable competitive advantages include:

- A highly differentiated and proven software platform (Gotham and Foundry) tailored for extremely complex and sensitive data environments, making substitution costly and risky.
- Extensive government relationships that provide steady, high-margin contracts with substantial barriers for new entrants due to security clearances and specific domain expertise.
- A growing commercial footprint where the company’s software increasingly addresses enterprise AI and data integration bottlenecks in industries undergoing digital transformation.
- Deep technical expertise in AI and machine learning, with ongoing investments integrating next-generation AI capabilities to maintain cutting-edge advantage.
- Strong customer engagement model that embeds Palantir software directly into customers’ operations, creating high switching costs and predictable revenue streams.

These features position Palantir uniquely at the intersection of geopolitics, AI, and big data analytics, a niche competitors find difficult to replicate quickly or at scale.

## What must go right

- Continued geopolitical instability and rising government spending on intelligence and defense-related data analytics.
- Successful scaling of commercial customer wins, especially enterprise adoption of Foundry’s AI-enhanced analytics capabilities.
- Palantir’s investments in AI integration result in meaningful platform differentiation, driving higher contract value and improved customer retention.
- The company enhances operating leverage, resulting in sustainable profitability improvements as revenue scales.
- Palantir maintains strong relationships with key government clients while expanding globally without losing contract terms or political support.

Execution in sales, product innovation, and margin discipline will be key to converting the sizable total addressable market (TAM) into durable financial returns.

## Key risks (central)

- Palantir’s ability to expand successfully into commercial sectors faces competition from established enterprise AI and analytics incumbents, including cloud providers and software giants.
- Heavy reliance on government contracts subjects Palantir to political and budgetary risks, including potential contract cancellations or reductions tied to shifting policies.
- The company’s complex sales cycle and high contract customization requirements could slow growth or lead to unpredictable revenue patterns.
- Potential regulatory and privacy-related scrutiny as the company handles sensitive data across various jurisdictions.
- Execution challenges managing rapid growth, AI integration, and operational scaling could pressure margins or stall platform innovation.

These risks reflect execution and competitive environment uncertainties rather than structural threats to Palantir’s core business model.

## Invalidation criteria (explicit)

This thesis is broken if one or more occur:

- Sustained stagnation or decline in government contract renewals or new wins due to political or budgetary constraints.
- Material loss of commercial customer traction resulting in flat or declining non-government revenue.
- Failure to demonstrate meaningful AI-driven product differentiation that improves contract economics and retention.
- Significant margin erosion despite revenue growth indicating inability to scale profitably.
- Severe reputational or regulatory issues that impair Palantir’s ability to operate in key markets or retain customers.

Any of these would require a fundamental reassessment of Palantir’s long-term growth and profitability outlook.

## Time horizon

- 5-10 years  
- Expect volatility driven by government budget cycles, geopolitical events, and AI innovation adoption timelines. The investment thesis is based on sustainable revenue growth and embedding Palantir’s technology as critical infrastructure within customers’ operations over several years.

## Potential portfolio role

- A growth-oriented position with exposure to data analytics, AI, and national security sectors.
- Provides diversification benefits through a hybrid government/commercial customer base.
- Can serve as a thematic play on enterprise digital transformation combined with rising geopolitical tensions.
- Requires understanding of long sales cycles and significant execution risk; position sizing should reflect these factors.

## Exit / trim rules

Consider trimming or exiting if:

- Government contract renewals significantly weaken or political headwinds increase materially.
- Commercial business fails to demonstrate consistent growth or margin expansion.
- AI and machine learning enhancements fail to translate into competitive advantage or improved financial metrics.
- Valuation materially exceeds the foreseeable long-term growth potential, or better risk-adjusted opportunities emerge.

## One-sentence summary

Palantir is a differentiated data analytics platform company uniquely positioned to benefit from rising geopolitical tensions and enterprise AI adoption through deeply embedded, mission-critical software that creates high switching costs and accelerating growth potential over the next decade.
```

## 4) Run Evaluator

```bash
python main.py

# Alternative using private helper scripts
# Windows PowerShell
.\evaluate.ps1

# Linux/macOS
./evaluate.sh
```

## 5) Resulting Log Entry (Excerpt)

Source file: [log/pltr.md](log/pltr.md)

```markdown
### SEC Filing Review: 10-K (2026-02-17) - 0001321655-26-000011
<!-- processed-sec-filing:0001321655-26-000011 -->
- Filing URL: https://www.sec.gov/Archives/edgar/data/1321655/000132165526000011/pltr-20251231.htm
- Processed on: 2026-04-23

Palantir’s 2025 10-K demonstrates continued validation of the core investment thesis pillars. Revenue diversified with 54% government and 46% commercial contribution, indicating solid commercial expansion as planned. The average revenue from the top 20 customers increased to $93.9 million, up from $64.6 million in 2024, supporting strength in account expansion and deepening customer relationships. The company’s AI platform (AIP) deployment and integration with existing platforms further underscores management’s successful innovation and investment in AI-driven differentiation, aligning with the thesis’ expectation of AI-enhanced product leadership.

Operating leverage trends appear positive with a focus on embedding software deeply into customer workflows and expanding sector-wide operating systems, indicating improving margin prospects. Palantir’s balance sheet remains strong with no indications of liquidity strain or margin erosion despite scale, and the 2025 filing remarks on expanding cloud partnerships and joint ventures that should further drive scalable growth. Risks around government budget dependency and competition are acknowledged but have not yet triggered invalidation criteria. Regulatory and reputational risks remain monitored, with no signs of material impact reported.

Given the structural growth validating key assumptions on government contracts, commercial traction, AI integration, and operating leverage, the thesis remains intact with no invalidation triggered. The timeline and growth opportunity appear stable or slightly improved from the prior year. Relative to opportunity cost, Palantir continues to occupy a unique niche at the AI and data infrastructure intersection with significant strategic advantages and high switching costs.

Verdict: Maintain  
Evidence: "54% government, 46% commercial revenue mix," "average revenue for top twenty customers ... $93.9 million, up from $64.6 million," deployment of AIP generative AI platform, continued investment in "Apollo," strong "operating leverage... profitability improvements," and no reported margin erosion or contract renewal weaknesses.
```

This demonstrates the canonical output shape: verdict + 2-3 evidence bullets + accession filing URL.

## 6) Optional: Run Leverage Evaluator (Independent Helper Tool)

The leverage evaluator is independent from the main thesis evaluator flow.

- It does **not** use the thesis content/body for analysis.
- It only uses ticker symbols derived from thesis filenames in [thesis](thesis) (for example `pltr.md` -> `PLTR`).
- It fetches the latest 10-K or 10-Q and writes leverage history files to [leverage](leverage).

Run directly:

```bash
python leverage-evaluator.py
```

Or use helper scripts:

```bash
# Windows PowerShell
.\leverage-evaluate.ps1

# Linux/macOS
./leverage-evaluate.sh
```

## 7) Leverage Output (Excerpt)

Example output from the leverage evaluator:

Source file: [leverage/pltr.md](leverage/pltr.md)

```markdown
### Leverage Review: 10-K (2026-02-17) - 0001321655-26-000011
<!-- processed-leverage-filing:0001321655-26-000011 -->
- Filing URL: https://www.sec.gov/Archives/edgar/data/1321655/000132165526000011/pltr-20251231.htm

#### Extracted Values

| Metric | Value |
|---|---|
| Company Name | Palantir Technologies Inc. |
| Period End | 2025-12-31 |
| Currency | USD |
| Shareholders' Equity | 7,488,011.00 |
| Total Assets | 8,900,392.00 |
| EBIT | 1,414,015.00 |

#### Calculated Leverage Ratios

| Ratio | Value |
|---|---|
| Debt-to-Equity | N/A |
| Debt-to-Assets | N/A |
| Net Debt / EBITDA | N/A |
| Interest Coverage (EBIT / Interest Expense) | N/A |
| Category (rule-based) | Unknown |

Final Leverage Verdict: Low Leverage
```
