# Pitch Guide

## 1. Core Pitch

Use this everywhere.

### One-liner

> SEC-driven thesis revalidation: keep an investment thesis in markdown, and automatically append a decision log (Hold/Trim/Exit/Watch) whenever a new 10-K/10-Q/8-K is filed.

### Two-sentence explainer (investor-friendly)

> I built a tool that monitors new SEC filings for tickers you track and re-validates your written investment thesis using a structured quarterly/annual/event framework. It outputs a short, evidence-based markdown entry and appends it to a durable decision log (with filing accession + URL) so you can review your own assumptions over time.

### What makes it different

- **Thesis-first** � you supply your thesis + invalidation criteria; the tool checks it against filings
- **Audit trail** � append-only log per ticker; idempotent "processed filing" markers
- **Form-specific rigor** � 10-K vs 10-Q vs 8-K instructions are different

### Call to action (pick ONE per post)

- "Try the canonical demo and tell me what breaks / what's missing."
- "If you write theses, I'm looking for 5�10 design partners."
- "Star the repo if you want updates."

---

## 2. How to Refer to the Repo/Demo When Links May Be Blocked

Use this consistent pattern:

| | |
|---|---|
| **Repo** | `GitHub: orri93/ai-investment-thesis` |
| **Demo** | In the repo, open `demo.md` (Canonical Demo) |
| **Quick start** | README has setup; `demo.md` shows end-to-end flow |

If you can include a link, include it once at the end. If not, don't apologize � just give the repo slug.

**Example phrasing (no links):**

> Search GitHub for `orri93/ai-investment-thesis`. Open `demo.md` for the canonical end-to-end demo.

**Memorable finder phrase:**

> "Type: orri93 ai investment thesis into GitHub search."

---

## 3. Where to Post

### Best-fit communities (process-oriented investors + builders)

**Reddit**
- **r/SecurityAnalysis** � best fit for thesis + revalidation
- **r/ValueInvesting** � frame as discipline + documentation
- **r/investing** � keep it beginner-friendly, avoid "alpha claims"
- **r/algotrading** � frame as pipeline + monitoring, not trading signals
- **r/stocks** � lighter version

**Hacker / builder channels**
- Hacker News ("Show HN: �") � if you can tell a clear story + include demo
- Indie Hackers � building-in-public angle
- GitHub / open-source circles: Python, LLM tooling, data pipelines

**X (Twitter) / LinkedIn**
- X: investors + builders; threads do well
- LinkedIn: emphasize "research workflow + governance + audit trail"

> **Rule:** Investors want discipline + time-saving. Builders want architecture + reproducibility. Same project, different framing.

---

## 4. Copy/Paste Posts

### A) r/SecurityAnalysis

**Title:** SEC-driven investment thesis revalidation (markdown thesis ? append-only decision log)

**Body:**

I built a small open-source tool that treats an investment thesis like a living document.

Workflow:

1. You write your thesis in markdown (including risks + explicit invalidation criteria).
2. The tool scans new SEC filings for your tickers (10-K / 10-Q / 8-K).
3. It appends a short, evidence-based "decision log" entry (Hold/Trim/Exit/Watch) to `log/<ticker>.md`, including the filing accession + SEC URL.
4. It's idempotent � stores a processed marker so the same filing won't be re-run.

If you want to see the end-to-end flow, there's a canonical demo in `demo.md`.

How to find it (no links): search GitHub for `orri93/ai-investment-thesis` and open `demo.md`.

What I'm looking for:
- Feedback from people who already write theses/memos
- What would make the output trustworthy (citations, exhibits, metrics, etc.)

---

### B) r/investing

**Title:** I made a tool to help me re-check my investment thesis when new SEC filings drop (open-source)

**Body:**

I tend to write an investment thesis when I buy � but I'm not great at revisiting it consistently.

So I built a small open-source tool:

- I keep each thesis in a markdown file (one file per ticker)
- When the company files a new 10-K/10-Q/8-K, the tool summarizes what changed and appends a short decision note to a log (Hold/Watch/Reduce/Exit)
- It includes the filing accession + SEC link so you can verify

If you want the step-by-step demo, open `demo.md` in the repo.

Find it by searching GitHub for: `orri93/ai-investment-thesis`

I'm looking for a few people to try it on 1�2 tickers and tell me:
- What parts feel useful vs noise
- What would increase trust in the output

---

### C) Indie Hackers

I'm building an open-source "thesis hygiene" tool for long-term stock investors.

You keep an investment thesis in markdown. When a new SEC filing appears (10-K / 10-Q / 8-K), the tool re-validates your thesis using a structured framework and appends a decision log entry (Hold/Trim/Exit/Watch) with a durable audit trail.

Canonical demo is in `demo.md`.

Find it on GitHub: search `orri93/ai-investment-thesis`.

Looking for 5�10 design partners:
- You already write theses/memos
- You'll try it on your watchlist
- You tell me what would make it trustworthy + useful (citations, exhibit parsing, etc.)

---

### D) X (Twitter) Thread

**Tweet 1**
> I built an open-source tool for SEC-driven thesis revalidation.

**Tweet 2**
> You keep a thesis in markdown (risks + invalidation criteria). When a new 10-K/10-Q/8-K drops, it appends a short decision log entry: Hold/Trim/Exit/Watch + evidence.

**Tweet 3**
> It's not "AI stock picks." It's thesis hygiene + an audit trail tied to filings + accession numbers.

**Tweet 4**
> If you want to see the exact end-to-end flow, there's a canonical demo: `demo.md`.

**Tweet 5**
> Find it by searching GitHub for: `orri93/ai-investment-thesis`.

**Tweet 6 (ask)**
> Looking for 5�10 investors who already write theses to test it on 1�2 tickers and tell me what would make it more trustworthy.

---

### E) LinkedIn

I've been working on an open-source workflow for investment thesis revalidation.

The idea: treat an investment thesis as a living document. For each ticker, keep your thesis in markdown (including risks and explicit invalidation criteria). When a new SEC filing appears (10-K / 10-Q / 8-K), the tool generates a short, evidence-based review and appends it to an audit-friendly decision log (including filing accession + SEC URL). It also prevents reprocessing the same filing.

If you'd like to see the end-to-end walkthrough, the repository includes a canonical demo in `demo.md`.

You can find the repo by searching GitHub for `orri93/ai-investment-thesis`.

I'm looking for a small group of early users who already write theses/memos and are willing to provide feedback on:
- What's useful vs noise
- What would increase trust (citations, exhibit parsing, extracted tables, etc.)

---

## 5. If Links Are Allowed

If you think links might work but want to be safe, do both:

1. Put the repo slug in the body
2. Put the URL in a comment / first reply

**Example body line:**

> Repo: `orri93/ai-investment-thesis` (GitHub). Canonical demo: `demo.md`.

**First comment:**

> https://github.com/orri93/ai-investment-thesis

---

## 6. Quick Wins Before Posting

- [ ] Rename README headline to: **"SEC-Driven Investment Thesis Revalidation (OpenAI + EDGAR)"**
- [ ] Add a "30-second demo" excerpt at top of README (5�15 lines showing a log entry shape)
- [ ] Add a "Who this is for / not for" section (reduces backlash in investor communities)
- [ ] Add a single CTA: "Try `demo.md` and open an issue with feedback"

---

## 7. Clarifying Question

Which audience do you want to target first?
